"""Content-addressed GUI verification receipt aggregation (VGO-041).

Wire interfaces:

* ``VisualRegressionReceipt@1``
* ``AccessibilityReceipt@1``
* ``InteractionReceipt@1``
* ``UiConstraintReceipt@1``
* ``GuiImprovementReceipt@1``
* ``GuiVerificationReceiptEnvelope@1`` — closed canonical aggregate
* ``GuiVerificationReceiptAggregator@1`` — deterministic assembler

Conflict policy
---------------
Aggregate immutable evidence references without elevating simulation,
integrity, structural, heuristic, or human claims beyond their declared
authority.  Content identity never upgrades analysis classification or
verification status.  Nested artifact and receipt identities rehash from
retained canonical bytes.

Accepted envelopes require all four verification receipt classes plus
invalidation, context, and patch evidence.  Rejected envelopes preserve
their rejection reasons.  Identical inputs produce an identical receipt
identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .identity import (
    GuiCanonicalIdentity,
    GuiIdentityError,
    artifact_digest,
    canonical_identity,
    model_identity,
    sha256_digest,
    verify_identity,
)
from .models import (
    AccessibilityReceipt,
    GuiImprovementProposal,
    GuiImprovementReceipt,
    InteractionReceipt,
    UiConstraintReceipt,
    UiContextPack,
    UiInvalidationPlan,
    VisualRegressionReceipt,
)
from .schema import (
    ACCESSIBILITY_RECEIPT_INTERFACE,
    ACCESSIBILITY_RECEIPT_SCHEMA,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    INTERACTION_RECEIPT_INTERFACE,
    INTERACTION_RECEIPT_SCHEMA,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_SCHEMA,
    UI_CONTEXT_PACK_INTERFACE,
    UI_INVALIDATION_PLAN_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_SCHEMA,
    AnalysisClassification,
    EvidenceLevel,
    GuiOptimizerDecodeError,
    ProposalDecision,
    VerificationStatus,
    optional_digest,
    optional_identifier,
    parse_enum,
    reject_unknown_fields,
    require_digest,
    require_identifier,
    require_mapping,
    require_text,
    unique_texts,
)


# ---------------------------------------------------------------------------
# Interface / schema / domain identities
# ---------------------------------------------------------------------------

GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE: Final = (
    "GuiVerificationReceiptEnvelope@1"
)
GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA: Final = (
    "gui-verification-receipt-envelope/v1"
)
GUI_VERIFICATION_RECEIPT_AGGREGATOR_INTERFACE: Final = (
    "GuiVerificationReceiptAggregator@1"
)
GUI_VERIFICATION_RECEIPT_AGGREGATOR_SCHEMA: Final = (
    "gui-verification-receipt-aggregator/v1"
)
GUI_VERIFICATION_RECEIPT_AGGREGATOR_VERSION: Final = (
    "gui-verification-receipt-aggregator@1.0.0"
)

DOMAIN_VISUAL_REGRESSION_RECEIPT: Final = "gui.visual-regression-receipt"
DOMAIN_ACCESSIBILITY_RECEIPT: Final = "gui.accessibility-receipt"
DOMAIN_INTERACTION_RECEIPT: Final = "gui.interaction-receipt"
DOMAIN_CONSTRAINT_RECEIPT: Final = "gui.constraint-receipt"
DOMAIN_IMPROVEMENT_RECEIPT: Final = "gui.improvement-receipt"
DOMAIN_VERIFICATION_ENVELOPE: Final = "gui.verification-receipt-envelope"
DOMAIN_INVALIDATION_PLAN: Final = "gui.invalidation-plan"
DOMAIN_CONTEXT_PACK: Final = "gui.context-pack"
DOMAIN_SCREENSHOT: Final = "gui.screenshot"
DOMAIN_PATCH: Final = "gui.patch"

VERIFICATION_RECEIPT_INTERFACES: Final[tuple[str, ...]] = (
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    ACCESSIBILITY_RECEIPT_INTERFACE,
    INTERACTION_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
)

CRITICAL_RECEIPT_INTERFACES: Final[frozenset[str]] = frozenset(
    {
        ACCESSIBILITY_RECEIPT_INTERFACE,
        INTERACTION_RECEIPT_INTERFACE,
        UI_CONSTRAINT_RECEIPT_INTERFACE,
    }
)

ACCEPTABLE_IMPROVEMENT_STATUSES: Final[frozenset[VerificationStatus]] = frozenset(
    {
        VerificationStatus.VERIFIED,
        VerificationStatus.INTEGRITY_VALID,
    }
)
BLOCKING_CRITICAL_STATUSES: Final[frozenset[VerificationStatus]] = frozenset(
    {
        VerificationStatus.UNVERIFIED,
        VerificationStatus.STALE,
        VerificationStatus.INVALID,
        VerificationStatus.SIMULATED,
    }
)

# Lower rank is a weaker authority ceiling.  The aggregate may only claim
# the weakest constituent label so no class is silently promoted.
_EVIDENCE_RANK: Final[Mapping[EvidenceLevel, int]] = {
    EvidenceLevel.SIMULATED: 0,
    EvidenceLevel.HEURISTIC: 1,
    EvidenceLevel.HUMAN_REVIEWED: 2,
    EvidenceLevel.AUTOMATED: 3,
    EvidenceLevel.STRUCTURAL: 4,
    EvidenceLevel.INTEGRITY: 5,
}
_ANALYSIS_RANK: Final[Mapping[AnalysisClassification, int]] = {
    AnalysisClassification.OPAQUE: 0,
    AnalysisClassification.HEURISTIC: 1,
    AnalysisClassification.CONSERVATIVE: 2,
    AnalysisClassification.EXACT: 3,
}
_VERIFICATION_RANK: Final[Mapping[VerificationStatus, int]] = {
    VerificationStatus.INVALID: 0,
    VerificationStatus.STALE: 1,
    VerificationStatus.SIMULATED: 2,
    VerificationStatus.UNVERIFIED: 3,
    VerificationStatus.STRUCTURALLY_VALID: 4,
    VerificationStatus.INTEGRITY_VALID: 5,
    VerificationStatus.VERIFIED: 6,
}

_IDENTITY_REF_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "cid",
        "digest",
        "domain",
        "interface",
        "receipt_id",
        "schema_version",
    }
)
_ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "accessibility_identities",
        "accessibility_receipts",
        "after_artifact_digests",
        "analysis_classification",
        "application_id",
        "authority_ceiling",
        "before_artifact_digests",
        "checks",
        "constraint_identities",
        "constraint_receipts",
        "context_pack_cid",
        "context_pack_digest",
        "context_pack_id",
        "decision",
        "envelope_cid",
        "envelope_digest",
        "evidence_levels",
        "interaction_identities",
        "interaction_receipts",
        "interface",
        "invalidation_plan",
        "invalidation_plan_id",
        "metrics",
        "patch_digest",
        "patch_scope",
        "proposal_id",
        "receipt",
        "receipt_identity",
        "rejection_reasons",
        "repository_revision",
        "scenario_inputs",
        "schema_version",
        "screen_id",
        "verification_status",
        "versions",
        "visual_identities",
        "visual_receipts",
    }
)
_ENVELOPE_IDENTITY_EXCLUDED: Final[frozenset[str]] = frozenset(
    {
        "envelope_cid",
        "envelope_digest",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GuiReceiptError(ValueError):
    """Raised when receipt identity, authority, or aggregation fails."""


class GuiReceiptIssueCode(str, Enum):
    """Stable reasons a receipt envelope cannot be accepted or decoded."""

    MISSING_VISUAL_RECEIPT = "missing_visual_receipt"
    MISSING_ACCESSIBILITY_RECEIPT = "missing_accessibility_receipt"
    MISSING_INTERACTION_RECEIPT = "missing_interaction_receipt"
    MISSING_CONSTRAINT_RECEIPT = "missing_constraint_receipt"
    MISSING_INVALIDATION_PLAN = "missing_invalidation_plan"
    MISSING_CONTEXT_PACK = "missing_context_pack"
    MISSING_PATCH_DIGEST = "missing_patch_digest"
    MISSING_REJECTION_REASONS = "missing_rejection_reasons"
    AUTHORITY_ELEVATION = "authority_elevation"
    CRITICAL_EVIDENCE_BLOCKED = "critical_evidence_blocked"
    REVISION_MISMATCH = "revision_mismatch"
    APPLICATION_MISMATCH = "application_mismatch"
    SCREEN_MISMATCH = "screen_mismatch"
    DUPLICATE_RECEIPT_ID = "duplicate_receipt_id"
    IDENTITY_MISMATCH = "identity_mismatch"
    ARTIFACT_REHASH_MISMATCH = "artifact_rehash_mismatch"
    UNKNOWN_FIELD = "unknown_field"
    MISSING_FIELD = "missing_field"


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def _parse_closed_enum(value: Any, enum_cls: type[Any], name: str) -> Any:
    """Accept a wire string or an already-parsed member of *enum_cls*."""

    if isinstance(value, enum_cls):
        return value
    if isinstance(value, Enum):
        value = value.value
    return parse_enum(value, enum_cls, name)


def _as_mapping(value: Any, label: str) -> dict[str, Any]:
    if type(value) is dict:
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        if type(payload) is not dict:
            raise GuiReceiptError(f"{label} to_dict() must return a mapping")
        return payload
    raise GuiReceiptError(f"{label} must be a closed mapping or model")


def _decode_model(value: Any, cls: type[Any], label: str) -> Any:
    if isinstance(value, cls):
        return value
    try:
        return cls.from_dict(_as_mapping(value, label))
    except GuiOptimizerDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize decode failures
        raise GuiReceiptError(f"{label} is not a valid {cls.__name__}") from exc


def _decode_models(
    values: Any,
    cls: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise GuiReceiptError(f"{label} must be a sequence")
    items = tuple(_decode_model(item, cls, f"{label} item") for item in values)
    seen: set[str] = set()
    for item in items:
        receipt_id = getattr(item, "receipt_id", "")
        if receipt_id in seen:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.DUPLICATE_RECEIPT_ID.value}: "
                f"duplicate {label} id {receipt_id!r}"
            )
        seen.add(receipt_id)
    return tuple(sorted(items, key=lambda item: item.receipt_id))


def _identity_for_payload(
    payload: Mapping[str, Any],
    *,
    domain: str,
    schema_version: str,
) -> GuiCanonicalIdentity:
    try:
        return canonical_identity(
            dict(payload),
            domain=domain,
            schema_version=schema_version,
        )
    except GuiIdentityError as exc:
        raise GuiReceiptError(str(exc)) from exc


def _identity_ref(
    identity: GuiCanonicalIdentity,
    *,
    receipt_id: str,
    interface: str,
    schema_version: str,
) -> dict[str, str]:
    return {
        "cid": identity.cid,
        "digest": identity.digest,
        "domain": identity.domain,
        "interface": interface,
        "receipt_id": receipt_id,
        "schema_version": schema_version,
    }


def _decode_identity_ref(value: Any, label: str) -> dict[str, str]:
    payload = require_mapping(value, label)
    reject_unknown_fields(payload, _IDENTITY_REF_FIELDS, label)
    return {
        "cid": require_text(payload.get("cid", ""), f"{label}.cid"),
        "digest": require_digest(payload.get("digest", ""), f"{label}.digest"),
        "domain": require_text(payload.get("domain", ""), f"{label}.domain"),
        "interface": require_text(
            payload.get("interface", ""), f"{label}.interface"
        ),
        "receipt_id": require_identifier(
            payload.get("receipt_id", ""), f"{label}.receipt_id"
        ),
        "schema_version": require_text(
            payload.get("schema_version", ""), f"{label}.schema_version"
        ),
    }


def visual_regression_receipt_identity(
    receipt: VisualRegressionReceipt | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``VisualRegressionReceipt@1``."""

    decoded = _decode_model(
        receipt, VisualRegressionReceipt, "VisualRegressionReceipt"
    )
    return _identity_for_payload(
        decoded.to_dict(),
        domain=DOMAIN_VISUAL_REGRESSION_RECEIPT,
        schema_version=VISUAL_REGRESSION_RECEIPT_SCHEMA,
    )


def accessibility_receipt_identity(
    receipt: AccessibilityReceipt | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``AccessibilityReceipt@1``."""

    decoded = _decode_model(
        receipt, AccessibilityReceipt, "AccessibilityReceipt"
    )
    return _identity_for_payload(
        decoded.to_dict(),
        domain=DOMAIN_ACCESSIBILITY_RECEIPT,
        schema_version=ACCESSIBILITY_RECEIPT_SCHEMA,
    )


def interaction_receipt_identity(
    receipt: InteractionReceipt | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``InteractionReceipt@1``."""

    decoded = _decode_model(receipt, InteractionReceipt, "InteractionReceipt")
    return _identity_for_payload(
        decoded.to_dict(),
        domain=DOMAIN_INTERACTION_RECEIPT,
        schema_version=INTERACTION_RECEIPT_SCHEMA,
    )


def constraint_receipt_identity(
    receipt: UiConstraintReceipt | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``UiConstraintReceipt@1``."""

    decoded = _decode_model(
        receipt, UiConstraintReceipt, "UiConstraintReceipt"
    )
    return _identity_for_payload(
        decoded.to_dict(),
        domain=DOMAIN_CONSTRAINT_RECEIPT,
        schema_version=UI_CONSTRAINT_RECEIPT_SCHEMA,
    )


def improvement_receipt_identity(
    receipt: GuiImprovementReceipt | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for ``GuiImprovementReceipt@1``."""

    decoded = _decode_model(
        receipt, GuiImprovementReceipt, "GuiImprovementReceipt"
    )
    return _identity_for_payload(
        decoded.to_dict(),
        domain=DOMAIN_IMPROVEMENT_RECEIPT,
        schema_version=GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    )


def receipt_identity(receipt: Any) -> GuiCanonicalIdentity:
    """Dispatch identity computation by closed receipt interface."""

    if isinstance(receipt, Mapping):
        interface = receipt.get("interface")
    else:
        interface = getattr(receipt, "interface", None)
    dispatch = {
        VISUAL_REGRESSION_RECEIPT_INTERFACE: visual_regression_receipt_identity,
        ACCESSIBILITY_RECEIPT_INTERFACE: accessibility_receipt_identity,
        INTERACTION_RECEIPT_INTERFACE: interaction_receipt_identity,
        UI_CONSTRAINT_RECEIPT_INTERFACE: constraint_receipt_identity,
        GUI_IMPROVEMENT_RECEIPT_INTERFACE: improvement_receipt_identity,
    }
    try:
        return dispatch[interface](receipt)
    except KeyError as exc:
        raise GuiReceiptError(
            f"unsupported receipt interface {interface!r}"
        ) from exc


def rehash_receipt_identity(identity: GuiCanonicalIdentity) -> GuiCanonicalIdentity:
    """Recompute a receipt identity from retained canonical bytes."""

    try:
        return identity.rehash()
    except GuiIdentityError as exc:
        raise GuiReceiptError(str(exc)) from exc


def verify_receipt_identity(
    identity: GuiCanonicalIdentity,
    receipt: Any,
) -> GuiCanonicalIdentity:
    """Require *identity* to match the recomputed receipt identity."""

    expected = receipt_identity(receipt)
    try:
        return verify_identity(
            identity,
            _as_mapping(receipt, "receipt"),
            domain=expected.domain,
            schema_version=expected.schema_version,
        )
    except GuiIdentityError as exc:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Authority labels
# ---------------------------------------------------------------------------


def _meet_enum(values: Sequence[Any], ranking: Mapping[Any, int], label: str) -> Any:
    if not values:
        raise GuiReceiptError(f"{label} cannot be derived from an empty set")
    return min(values, key=lambda item: ranking[item])


def authority_ceiling_for(
    levels: Sequence[EvidenceLevel | str],
) -> EvidenceLevel:
    """Return the weakest declared evidence level (never an upgrade)."""

    parsed = tuple(
        _parse_closed_enum(item, EvidenceLevel, "evidence_level") for item in levels
    )
    return _meet_enum(parsed, _EVIDENCE_RANK, "authority_ceiling")


def analysis_classification_for(
    values: Sequence[AnalysisClassification | str],
) -> AnalysisClassification:
    parsed = tuple(
        _parse_closed_enum(item, AnalysisClassification, "analysis_classification")
        for item in values
    )
    return _meet_enum(parsed, _ANALYSIS_RANK, "analysis_classification")


def _forbid_elevation(
    claimed: EvidenceLevel,
    computed: EvidenceLevel,
    *,
    label: str,
) -> None:
    if _EVIDENCE_RANK[claimed] > _EVIDENCE_RANK[computed]:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.AUTHORITY_ELEVATION.value}: "
            f"{label} cannot elevate {computed.value} to {claimed.value}"
        )


def _critical_receipts(
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
) -> tuple[tuple[str, Any], ...]:
    items: list[tuple[str, Any]] = []
    items.extend(
        (ACCESSIBILITY_RECEIPT_INTERFACE, item) for item in accessibility
    )
    items.extend((INTERACTION_RECEIPT_INTERFACE, item) for item in interaction)
    items.extend((UI_CONSTRAINT_RECEIPT_INTERFACE, item) for item in constraints)
    return tuple(items)


# ---------------------------------------------------------------------------
# Envelope bindings
# ---------------------------------------------------------------------------


def _require_shared_scope(
    *,
    application_id: str,
    screen_id: str,
    repository_revision: str,
    receipts: Sequence[Any],
    invalidation_plan: UiInvalidationPlan | None,
    context_pack: UiContextPack | None,
    proposal: GuiImprovementProposal | None,
) -> None:
    for receipt in receipts:
        if receipt.application_id != application_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.APPLICATION_MISMATCH.value}: "
                f"{receipt.receipt_id} application_id mismatch"
            )
        if receipt.screen_id != screen_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.SCREEN_MISMATCH.value}: "
                f"{receipt.receipt_id} screen_id mismatch"
            )
        if receipt.repository_revision != repository_revision:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.REVISION_MISMATCH.value}: "
                f"{receipt.receipt_id} repository_revision mismatch"
            )
    if context_pack is not None:
        if context_pack.application_id != application_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.APPLICATION_MISMATCH.value}: "
                "context pack application_id mismatch"
            )
        if context_pack.screen_id != screen_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.SCREEN_MISMATCH.value}: "
                "context pack screen_id mismatch"
            )
    if proposal is not None:
        if proposal.application_id != application_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.APPLICATION_MISMATCH.value}: "
                "proposal application_id mismatch"
            )
        if proposal.screen_id != screen_id:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.SCREEN_MISMATCH.value}: "
                "proposal screen_id mismatch"
            )
    del invalidation_plan


def _scenario_inputs(
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
) -> tuple[dict[str, Any], ...]:
    by_id: dict[str, dict[str, Any]] = {}
    for receipt in visual:
        by_id[receipt.scenario_id] = {
            "browser": receipt.browser,
            "browser_version": receipt.browser_version,
            "color_scheme": receipt.color_scheme,
            "locale": receipt.locale,
            "scenario_id": receipt.scenario_id,
            "text_scale_percent": receipt.text_scale_percent,
            "viewport": receipt.viewport.to_dict(),
        }
    for receipt in (*accessibility, *interaction):
        by_id.setdefault(receipt.scenario_id, {"scenario_id": receipt.scenario_id})
    return tuple(by_id[key] for key in sorted(by_id))


def _versions(
    visual: Sequence[VisualRegressionReceipt],
) -> dict[str, Any]:
    component_ids: list[str] = []
    for receipt in visual:
        component_ids.extend(receipt.component_version_ids)
    unique = tuple(sorted(set(component_ids)))
    return {
        "accessibility_receipt_schema": ACCESSIBILITY_RECEIPT_SCHEMA,
        "component_version_ids": list(unique),
        "constraint_receipt_schema": UI_CONSTRAINT_RECEIPT_SCHEMA,
        "envelope_schema": GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA,
        "improvement_receipt_schema": GUI_IMPROVEMENT_RECEIPT_SCHEMA,
        "interaction_receipt_schema": INTERACTION_RECEIPT_SCHEMA,
        "visual_receipt_schema": VISUAL_REGRESSION_RECEIPT_SCHEMA,
    }


def _artifact_digests(
    visual: Sequence[VisualRegressionReceipt],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    before = tuple(sorted({receipt.baseline_digest for receipt in visual}))
    after = tuple(sorted({receipt.screenshot_digest for receipt in visual}))
    return before, after


def _checks(
    constraints: Sequence[UiConstraintReceipt],
) -> dict[str, Any]:
    check_ids: list[str] = []
    statuses: list[str] = []
    violated: list[str] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for receipt in constraints:
        for check_id, status in zip(
            receipt.check_ids, receipt.statuses, strict=True
        ):
            if check_id in seen:
                raise GuiReceiptError(
                    f"{GuiReceiptIssueCode.DUPLICATE_RECEIPT_ID.value}: "
                    f"duplicate check_id {check_id!r}"
                )
            seen.add(check_id)
            check_ids.append(check_id)
            statuses.append(status.value)
        violated.extend(receipt.violated_check_ids)
        unsupported.extend(receipt.unsupported_check_ids)
    return {
        "check_ids": check_ids,
        "statuses": statuses,
        "unsupported_check_ids": list(unsupported),
        "violated_check_ids": list(violated),
    }


def _metrics(
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
) -> dict[str, int | float]:
    pixel = 0.0
    structural = 0.0
    shifts = 0
    missing = 0
    extra = 0
    for receipt in visual:
        pixel = max(pixel, float(receipt.pixel_diff_percent))
        structural = max(structural, float(receipt.structural_diff_percent))
        shifts += receipt.unexpected_layout_shift_count
        missing += receipt.missing_control_count
        extra += receipt.extra_control_count
    passes = sum(item.automated_pass_count for item in accessibility)
    violations = sum(item.violation_count for item in accessibility)
    unresolved = sum(
        len(item.unresolved_observation_ids) for item in interaction
    )
    violated_checks = sum(len(item.violated_check_ids) for item in constraints)
    return {
        "automated_pass_count": passes,
        "extra_control_count": extra,
        "invariant_violation_count": violated_checks,
        "missing_control_count": missing,
        "pixel_diff_percent": pixel,
        "structural_diff_percent": structural,
        "unexpected_layout_shift_count": shifts,
        "unresolved_observation_count": unresolved,
        "violation_count": violations,
    }


def _evidence_levels(
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
) -> dict[str, list[str]]:
    return {
        "accessibility": [item.evidence_level.value for item in accessibility],
        "constraint": [item.evidence_level.value for item in constraints],
        "interaction": [item.evidence_level.value for item in interaction],
        "visual": [item.evidence_level.value for item in visual],
    }


def _patch_scope(
    *,
    invalidation_plan: UiInvalidationPlan | None,
    proposal: GuiImprovementProposal | None,
) -> dict[str, list[str]]:
    file_paths: list[str] = []
    component_ids: list[str] = []
    scenario_ids: list[str] = []
    check_ids: list[str] = []
    if proposal is not None:
        file_paths.extend(proposal.intended_file_paths)
        component_ids.extend(proposal.intended_component_ids)
    if invalidation_plan is not None:
        component_ids.extend(invalidation_plan.affected_component_ids)
        scenario_ids.extend(invalidation_plan.affected_scenario_ids)
        check_ids.extend(invalidation_plan.affected_check_ids)
    return {
        "affected_check_ids": sorted(set(check_ids)),
        "affected_component_ids": sorted(set(component_ids)),
        "affected_scenario_ids": sorted(set(scenario_ids)),
        "file_paths": sorted(set(file_paths)),
    }


def _declared_levels(
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
) -> tuple[EvidenceLevel, ...]:
    levels: list[EvidenceLevel] = []
    for group in (visual, accessibility, interaction, constraints):
        levels.extend(item.evidence_level for item in group)
    return tuple(levels)


def _declared_analysis(
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
    proposal: GuiImprovementProposal | None,
) -> tuple[AnalysisClassification, ...]:
    values: list[AnalysisClassification] = []
    for group in (visual, accessibility, interaction, constraints):
        values.extend(item.analysis_classification for item in group)
    if proposal is not None:
        values.append(proposal.analysis_classification)
    return tuple(values)


def _identity_refs_for(
    receipts: Sequence[Any],
    identity_fn: Any,
    *,
    interface: str,
    schema_version: str,
) -> tuple[dict[str, str], ...]:
    refs: list[dict[str, str]] = []
    for receipt in receipts:
        identity = identity_fn(receipt)
        identity.rehash()
        refs.append(
            _identity_ref(
                identity,
                receipt_id=receipt.receipt_id,
                interface=interface,
                schema_version=schema_version,
            )
        )
    return tuple(refs)


# ---------------------------------------------------------------------------
# Envelope record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuiVerificationReceiptEnvelope:
    """Closed canonical aggregate of GUI verification receipts."""

    application_id: str
    screen_id: str
    repository_revision: str
    proposal_id: str
    decision: ProposalDecision
    verification_status: VerificationStatus
    analysis_classification: AnalysisClassification
    authority_ceiling: EvidenceLevel
    receipt: GuiImprovementReceipt
    visual_receipts: tuple[VisualRegressionReceipt, ...]
    accessibility_receipts: tuple[AccessibilityReceipt, ...]
    interaction_receipts: tuple[InteractionReceipt, ...]
    constraint_receipts: tuple[UiConstraintReceipt, ...]
    visual_identities: tuple[dict[str, str], ...]
    accessibility_identities: tuple[dict[str, str], ...]
    interaction_identities: tuple[dict[str, str], ...]
    constraint_identities: tuple[dict[str, str], ...]
    receipt_identity: dict[str, str]
    invalidation_plan_id: str
    invalidation_plan: UiInvalidationPlan | None
    context_pack_id: str
    context_pack_digest: str
    context_pack_cid: str
    patch_digest: str
    patch_scope: dict[str, list[str]]
    scenario_inputs: tuple[dict[str, Any], ...]
    versions: dict[str, Any]
    before_artifact_digests: tuple[str, ...]
    after_artifact_digests: tuple[str, ...]
    checks: dict[str, Any]
    metrics: dict[str, int | float]
    evidence_levels: dict[str, list[str]]
    rejection_reasons: tuple[str, ...]
    interface: str = GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE
    schema_version: str = GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA

    def identity_payload(self) -> dict[str, Any]:
        """Canonical preimage excluding the envelope's own CID/digest."""

        return {
            "accessibility_identities": [
                dict(item) for item in self.accessibility_identities
            ],
            "accessibility_receipts": [
                item.to_dict() for item in self.accessibility_receipts
            ],
            "after_artifact_digests": list(self.after_artifact_digests),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "authority_ceiling": self.authority_ceiling.value,
            "before_artifact_digests": list(self.before_artifact_digests),
            "checks": {
                "check_ids": list(self.checks["check_ids"]),
                "statuses": list(self.checks["statuses"]),
                "unsupported_check_ids": list(
                    self.checks["unsupported_check_ids"]
                ),
                "violated_check_ids": list(self.checks["violated_check_ids"]),
            },
            "constraint_identities": [
                dict(item) for item in self.constraint_identities
            ],
            "constraint_receipts": [
                item.to_dict() for item in self.constraint_receipts
            ],
            "context_pack_cid": self.context_pack_cid,
            "context_pack_digest": self.context_pack_digest,
            "context_pack_id": self.context_pack_id,
            "decision": self.decision.value,
            "evidence_levels": {
                key: list(values)
                for key, values in sorted(self.evidence_levels.items())
            },
            "interaction_identities": [
                dict(item) for item in self.interaction_identities
            ],
            "interaction_receipts": [
                item.to_dict() for item in self.interaction_receipts
            ],
            "interface": self.interface,
            "invalidation_plan": (
                None
                if self.invalidation_plan is None
                else self.invalidation_plan.to_dict()
            ),
            "invalidation_plan_id": self.invalidation_plan_id,
            "metrics": dict(sorted(self.metrics.items())),
            "patch_digest": self.patch_digest,
            "patch_scope": {
                key: list(values)
                for key, values in sorted(self.patch_scope.items())
            },
            "proposal_id": self.proposal_id,
            "receipt": self.receipt.to_dict(),
            "receipt_identity": dict(self.receipt_identity),
            "rejection_reasons": list(self.rejection_reasons),
            "repository_revision": self.repository_revision,
            "scenario_inputs": [dict(item) for item in self.scenario_inputs],
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "verification_status": self.verification_status.value,
            "versions": {
                "accessibility_receipt_schema": self.versions[
                    "accessibility_receipt_schema"
                ],
                "component_version_ids": list(
                    self.versions["component_version_ids"]
                ),
                "constraint_receipt_schema": self.versions[
                    "constraint_receipt_schema"
                ],
                "envelope_schema": self.versions["envelope_schema"],
                "improvement_receipt_schema": self.versions[
                    "improvement_receipt_schema"
                ],
                "interaction_receipt_schema": self.versions[
                    "interaction_receipt_schema"
                ],
                "visual_receipt_schema": self.versions["visual_receipt_schema"],
            },
            "visual_identities": [dict(item) for item in self.visual_identities],
            "visual_receipts": [item.to_dict() for item in self.visual_receipts],
        }

    @property
    def identity(self) -> GuiCanonicalIdentity:
        return envelope_identity(self)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        identity = envelope_identity_from_payload(payload)
        payload["envelope_cid"] = identity.cid
        payload["envelope_digest"] = identity.digest
        return payload

    def canonical_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def rehash(self) -> GuiCanonicalIdentity:
        return rehash_receipt_identity(self.identity)

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any] | Any
    ) -> GuiVerificationReceiptEnvelope:
        return decode_verification_envelope(value)


def envelope_identity_from_payload(
    payload: Mapping[str, Any],
) -> GuiCanonicalIdentity:
    body = dict(payload)
    for key in _ENVELOPE_IDENTITY_EXCLUDED:
        body.pop(key, None)
    return _identity_for_payload(
        body,
        domain=DOMAIN_VERIFICATION_ENVELOPE,
        schema_version=GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA,
    )


def envelope_identity(
    envelope: GuiVerificationReceiptEnvelope | Mapping[str, Any],
) -> GuiCanonicalIdentity:
    """Domain-separated identity for the closed aggregate envelope."""

    if isinstance(envelope, GuiVerificationReceiptEnvelope):
        return envelope_identity_from_payload(envelope.identity_payload())
    payload = _as_mapping(envelope, "envelope")
    return envelope_identity_from_payload(payload)


# ---------------------------------------------------------------------------
# Artifact rehash
# ---------------------------------------------------------------------------


def bind_artifact_material(
    material: Any,
    *,
    domain: str,
    claimed_digest: str | None = None,
) -> str:
    """Digest *material* and optionally require it to match *claimed_digest*."""

    if isinstance(material, (bytes, bytearray, memoryview)):
        digest = sha256_digest(bytes(material))
    else:
        digest = artifact_digest(material, domain=domain).digest
    if claimed_digest is not None and digest != claimed_digest:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.ARTIFACT_REHASH_MISMATCH.value}: "
            f"claimed {claimed_digest} != recomputed {digest}"
        )
    return digest


def rehash_nested_artifacts(
    envelope: GuiVerificationReceiptEnvelope,
    *,
    artifacts: Mapping[str, Any] | None = None,
) -> GuiVerificationReceiptEnvelope:
    """Rehash nested receipt identities and optional artifact preimages.

    *artifacts* maps a claimed ``sha256:<hex>`` digest onto either raw bytes
    or structured material.  Every nested receipt identity is rehashed from
    its retained canonical bytes and must match the envelope's stored refs.
    """

    groups = (
        (
            envelope.visual_receipts,
            envelope.visual_identities,
            visual_regression_receipt_identity,
            DOMAIN_VISUAL_REGRESSION_RECEIPT,
        ),
        (
            envelope.accessibility_receipts,
            envelope.accessibility_identities,
            accessibility_receipt_identity,
            DOMAIN_ACCESSIBILITY_RECEIPT,
        ),
        (
            envelope.interaction_receipts,
            envelope.interaction_identities,
            interaction_receipt_identity,
            DOMAIN_INTERACTION_RECEIPT,
        ),
        (
            envelope.constraint_receipts,
            envelope.constraint_identities,
            constraint_receipt_identity,
            DOMAIN_CONSTRAINT_RECEIPT,
        ),
    )
    for receipts, refs, identity_fn, domain in groups:
        if len(receipts) != len(refs):
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
                f"{domain} receipt/identity count mismatch"
            )
        for receipt, claimed in zip(receipts, refs, strict=True):
            identity = identity_fn(receipt)
            rehash_receipt_identity(identity)
            if (
                identity.cid != claimed["cid"]
                or identity.digest != claimed["digest"]
                or identity.domain != claimed["domain"]
            ):
                raise GuiReceiptError(
                    f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
                    f"{receipt.receipt_id} identity does not rehash"
                )
            verify_receipt_identity(identity, receipt)

    improvement = improvement_receipt_identity(envelope.receipt)
    rehash_receipt_identity(improvement)
    if (
        improvement.cid != envelope.receipt_identity["cid"]
        or improvement.digest != envelope.receipt_identity["digest"]
    ):
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
            "improvement receipt identity does not rehash"
        )

    envelope_id = envelope.rehash()
    claimed_digest = envelope.to_dict().get("envelope_digest")
    if claimed_digest and claimed_digest != envelope_id.digest:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
            "envelope digest does not rehash"
        )

    if artifacts:
        claimed_artifacts = {
            *envelope.before_artifact_digests,
            *envelope.after_artifact_digests,
        }
        if envelope.patch_digest:
            claimed_artifacts.add(envelope.patch_digest)
        for digest, material in artifacts.items():
            require_digest(digest, "artifact digest")
            domain = (
                DOMAIN_PATCH if digest == envelope.patch_digest else DOMAIN_SCREENSHOT
            )
            bind_artifact_material(
                material, domain=domain, claimed_digest=digest
            )
            if digest not in claimed_artifacts:
                raise GuiReceiptError(
                    f"{GuiReceiptIssueCode.ARTIFACT_REHASH_MISMATCH.value}: "
                    f"artifact {digest} is not bound by the envelope"
                )
    return envelope


def verify_envelope(
    envelope: GuiVerificationReceiptEnvelope,
    *,
    artifacts: Mapping[str, Any] | None = None,
) -> GuiVerificationReceiptEnvelope:
    """Fail closed unless the envelope, nested receipts, and artifacts rehash."""

    if (
        envelope.interface != GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE
        or envelope.schema_version != GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA
    ):
        raise GuiReceiptError("envelope metadata does not match the profile")
    recomputed = aggregate_verification_receipts(
        visual_receipts=envelope.visual_receipts,
        accessibility_receipts=envelope.accessibility_receipts,
        interaction_receipts=envelope.interaction_receipts,
        constraint_receipts=envelope.constraint_receipts,
        decision=envelope.decision,
        proposal_id=envelope.proposal_id,
        application_id=envelope.application_id,
        screen_id=envelope.screen_id,
        repository_revision=envelope.repository_revision,
        invalidation_plan=envelope.invalidation_plan,
        context_pack_id=envelope.context_pack_id,
        context_pack_digest=envelope.context_pack_digest,
        context_pack_cid=envelope.context_pack_cid,
        patch_digest=envelope.patch_digest,
        rejection_reasons=list(envelope.rejection_reasons),
        receipt_id=envelope.receipt.receipt_id,
        verification_status=envelope.verification_status,
        analysis_classification=envelope.analysis_classification,
        authority_ceiling=envelope.authority_ceiling,
    )
    if recomputed.identity.digest != envelope.identity.digest:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
            "envelope does not reproduce from nested evidence"
        )
    rehash_nested_artifacts(envelope, artifacts=artifacts)
    return envelope


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _require_accept_evidence(
    *,
    visual: Sequence[VisualRegressionReceipt],
    accessibility: Sequence[AccessibilityReceipt],
    interaction: Sequence[InteractionReceipt],
    constraints: Sequence[UiConstraintReceipt],
    invalidation_plan: UiInvalidationPlan | None,
    context_pack_id: str,
    patch_digest: str,
    rejection_reasons: Sequence[str],
) -> None:
    if not visual:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_VISUAL_RECEIPT.value}: "
            "accepted receipt requires VisualRegressionReceipt@1"
        )
    if not accessibility:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_ACCESSIBILITY_RECEIPT.value}: "
            "accepted receipt requires AccessibilityReceipt@1"
        )
    if not interaction:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_INTERACTION_RECEIPT.value}: "
            "accepted receipt requires InteractionReceipt@1"
        )
    if not constraints:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_CONSTRAINT_RECEIPT.value}: "
            "accepted receipt requires UiConstraintReceipt@1"
        )
    if invalidation_plan is None:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_INVALIDATION_PLAN.value}: "
            "accepted receipt requires invalidation evidence"
        )
    if not context_pack_id:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_CONTEXT_PACK.value}: "
            "accepted receipt requires context-pack evidence"
        )
    if not patch_digest:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_PATCH_DIGEST.value}: "
            "accepted receipt requires patch evidence"
        )
    if rejection_reasons:
        raise GuiReceiptError(
            "accepted receipt cannot carry rejection reasons"
        )
    for interface, receipt in _critical_receipts(
        accessibility, interaction, constraints
    ):
        if receipt.verification_status in BLOCKING_CRITICAL_STATUSES:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.CRITICAL_EVIDENCE_BLOCKED.value}: "
                f"{interface} {receipt.receipt_id} is "
                f"{receipt.verification_status.value}"
            )


def aggregate_verification_receipts(
    *,
    visual_receipts: Sequence[Any] | None = None,
    accessibility_receipts: Sequence[Any] | None = None,
    interaction_receipts: Sequence[Any] | None = None,
    constraint_receipts: Sequence[Any] | None = None,
    decision: ProposalDecision | str,
    proposal_id: str,
    application_id: str,
    screen_id: str,
    repository_revision: str,
    invalidation_plan: UiInvalidationPlan | Mapping[str, Any] | None = None,
    context_pack: UiContextPack | Mapping[str, Any] | None = None,
    context_pack_id: str = "",
    context_pack_digest: str = "",
    context_pack_cid: str = "",
    patch_digest: str = "",
    patch_material: Any = None,
    proposal: GuiImprovementProposal | Mapping[str, Any] | None = None,
    rejection_reasons: Sequence[str] | None = None,
    receipt_id: str = "",
    verification_status: VerificationStatus | str | None = None,
    analysis_classification: AnalysisClassification | str | None = None,
    authority_ceiling: EvidenceLevel | str | None = None,
) -> GuiVerificationReceiptEnvelope:
    """Assemble a closed, content-addressed improvement receipt envelope."""

    visual = _decode_models(
        visual_receipts or (), VisualRegressionReceipt, "visual_receipts"
    )
    accessibility = _decode_models(
        accessibility_receipts or (),
        AccessibilityReceipt,
        "accessibility_receipts",
    )
    interaction = _decode_models(
        interaction_receipts or (), InteractionReceipt, "interaction_receipts"
    )
    constraints = _decode_models(
        constraint_receipts or (), UiConstraintReceipt, "constraint_receipts"
    )
    plan = (
        None
        if invalidation_plan is None
        else _decode_model(
            invalidation_plan, UiInvalidationPlan, "invalidation_plan"
        )
    )
    pack = (
        None
        if context_pack is None
        else _decode_model(context_pack, UiContextPack, "context_pack")
    )
    proposal_model = (
        None
        if proposal is None
        else _decode_model(proposal, GuiImprovementProposal, "proposal")
    )

    decision_value = _parse_closed_enum(decision, ProposalDecision, "decision")
    application = require_identifier(application_id, "application_id")
    screen = require_identifier(screen_id, "screen_id")
    revision = require_text(repository_revision, "repository_revision")
    proposal_identifier = require_identifier(proposal_id, "proposal_id")
    if proposal_model is not None and proposal_model.proposal_id != proposal_identifier:
        raise GuiReceiptError("proposal_id does not match the supplied proposal")

    pack_id = optional_identifier(context_pack_id, "context_pack_id")
    if pack is not None:
        if pack_id and pack_id != pack.pack_id:
            raise GuiReceiptError("context_pack_id does not match the supplied pack")
        pack_id = pack.pack_id
    plan_id = plan.plan_id if plan is not None else ""

    digest = optional_digest(patch_digest, "patch_digest")
    if patch_material is not None:
        digest = bind_artifact_material(
            patch_material,
            domain=DOMAIN_PATCH,
            claimed_digest=digest or None,
        )

    reasons = unique_texts(
        list(rejection_reasons or []), "rejection_reasons"
    )

    _require_shared_scope(
        application_id=application,
        screen_id=screen,
        repository_revision=revision,
        receipts=(*visual, *accessibility, *interaction, *constraints),
        invalidation_plan=plan,
        context_pack=pack,
        proposal=proposal_model,
    )

    if decision_value is ProposalDecision.ACCEPT:
        _require_accept_evidence(
            visual=visual,
            accessibility=accessibility,
            interaction=interaction,
            constraints=constraints,
            invalidation_plan=plan,
            context_pack_id=pack_id,
            patch_digest=digest,
            rejection_reasons=reasons,
        )
    elif decision_value is ProposalDecision.REJECT and not reasons:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_REJECTION_REASONS.value}: "
            "rejected receipt requires nonempty rejection reasons"
        )

    declared_levels = _declared_levels(
        visual, accessibility, interaction, constraints
    )
    computed_ceiling = (
        authority_ceiling_for(declared_levels)
        if declared_levels
        else EvidenceLevel.SIMULATED
    )
    if authority_ceiling is None:
        ceiling = computed_ceiling
    else:
        ceiling = _parse_closed_enum(
            authority_ceiling, EvidenceLevel, "authority_ceiling"
        )
        _forbid_elevation(ceiling, computed_ceiling, label="authority_ceiling")

    declared_analysis = _declared_analysis(
        visual, accessibility, interaction, constraints, proposal_model
    )
    computed_analysis = (
        analysis_classification_for(declared_analysis)
        if declared_analysis
        else AnalysisClassification.OPAQUE
    )
    if analysis_classification is None:
        analysis = computed_analysis
    else:
        analysis = _parse_closed_enum(
            analysis_classification,
            AnalysisClassification,
            "analysis_classification",
        )
        if _ANALYSIS_RANK[analysis] > _ANALYSIS_RANK[computed_analysis]:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.AUTHORITY_ELEVATION.value}: "
                "analysis_classification cannot exceed declared constituents"
            )

    if verification_status is None:
        if decision_value is ProposalDecision.ACCEPT:
            status = VerificationStatus.VERIFIED
        elif decision_value is ProposalDecision.REJECT:
            status = VerificationStatus.INVALID
        else:
            status = VerificationStatus.UNVERIFIED
    else:
        status = _parse_closed_enum(
            verification_status, VerificationStatus, "verification_status"
        )
    if (
        decision_value is ProposalDecision.ACCEPT
        and status not in ACCEPTABLE_IMPROVEMENT_STATUSES
    ):
        raise GuiReceiptError(
            "accepted receipt requires verified or integrity_valid status"
        )

    visual_ids = [item.receipt_id for item in visual]
    a11y_ids = [item.receipt_id for item in accessibility]
    interaction_ids = [item.receipt_id for item in interaction]
    constraint_ids = [item.receipt_id for item in constraints]

    seed = {
        "accessibility_receipt_ids": a11y_ids,
        "analysis_classification": analysis.value,
        "application_id": application,
        "constraint_receipt_ids": constraint_ids,
        "context_pack_id": pack_id,
        "decision": decision_value.value,
        "interaction_receipt_ids": interaction_ids,
        "invalidation_plan_id": plan_id,
        "patch_digest": digest,
        "proposal_id": proposal_identifier,
        "rejection_reasons": list(reasons),
        "repository_revision": revision,
        "screen_id": screen,
        "verification_status": status.value,
        "visual_receipt_ids": visual_ids,
    }
    derived_id = (
        receipt_id
        if receipt_id
        else f"receipt:improvement:{_identity_for_payload(seed, domain=DOMAIN_IMPROVEMENT_RECEIPT, schema_version=GUI_IMPROVEMENT_RECEIPT_SCHEMA).hexdigest[:16]}"
    )
    improvement = GuiImprovementReceipt(
        receipt_id=require_identifier(derived_id, "receipt_id"),
        proposal_id=proposal_identifier,
        application_id=application,
        screen_id=screen,
        repository_revision=revision,
        decision=decision_value.value,
        visual_receipt_ids=visual_ids,
        accessibility_receipt_ids=a11y_ids,
        interaction_receipt_ids=interaction_ids,
        constraint_receipt_ids=constraint_ids,
        invalidation_plan_id=plan_id,
        context_pack_id=pack_id,
        patch_digest=digest,
        rejection_reasons=list(reasons),
        analysis_classification=analysis.value,
        verification_status=status.value,
        interface=GUI_IMPROVEMENT_RECEIPT_INTERFACE,
        schema_version=GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    )

    pack_digest = optional_digest(context_pack_digest, "context_pack_digest")
    pack_cid = context_pack_cid if context_pack_cid else ""
    if pack is not None:
        pack_identity = model_identity(pack, domain=DOMAIN_CONTEXT_PACK)
        if pack_digest and pack_digest != pack_identity.digest:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
                "context pack digest does not match the supplied pack"
            )
        if pack_cid and pack_cid != pack_identity.cid:
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
                "context pack CID does not match the supplied pack"
            )
        pack_digest = pack_identity.digest
        pack_cid = pack_identity.cid
    if pack_cid:
        require_text(pack_cid, "context_pack_cid")

    improvement_identity = improvement_receipt_identity(improvement)
    before, after = _artifact_digests(visual)
    envelope = GuiVerificationReceiptEnvelope(
        application_id=application,
        screen_id=screen,
        repository_revision=revision,
        proposal_id=proposal_identifier,
        decision=decision_value,
        verification_status=status,
        analysis_classification=analysis,
        authority_ceiling=ceiling,
        receipt=improvement,
        visual_receipts=visual,
        accessibility_receipts=accessibility,
        interaction_receipts=interaction,
        constraint_receipts=constraints,
        visual_identities=_identity_refs_for(
            visual,
            visual_regression_receipt_identity,
            interface=VISUAL_REGRESSION_RECEIPT_INTERFACE,
            schema_version=VISUAL_REGRESSION_RECEIPT_SCHEMA,
        ),
        accessibility_identities=_identity_refs_for(
            accessibility,
            accessibility_receipt_identity,
            interface=ACCESSIBILITY_RECEIPT_INTERFACE,
            schema_version=ACCESSIBILITY_RECEIPT_SCHEMA,
        ),
        interaction_identities=_identity_refs_for(
            interaction,
            interaction_receipt_identity,
            interface=INTERACTION_RECEIPT_INTERFACE,
            schema_version=INTERACTION_RECEIPT_SCHEMA,
        ),
        constraint_identities=_identity_refs_for(
            constraints,
            constraint_receipt_identity,
            interface=UI_CONSTRAINT_RECEIPT_INTERFACE,
            schema_version=UI_CONSTRAINT_RECEIPT_SCHEMA,
        ),
        receipt_identity=_identity_ref(
            improvement_identity,
            receipt_id=improvement.receipt_id,
            interface=GUI_IMPROVEMENT_RECEIPT_INTERFACE,
            schema_version=GUI_IMPROVEMENT_RECEIPT_SCHEMA,
        ),
        invalidation_plan_id=plan_id,
        invalidation_plan=plan,
        context_pack_id=pack_id,
        context_pack_digest=pack_digest,
        context_pack_cid=pack_cid,
        patch_digest=digest,
        patch_scope=_patch_scope(
            invalidation_plan=plan, proposal=proposal_model
        ),
        scenario_inputs=_scenario_inputs(visual, accessibility, interaction),
        versions=_versions(visual),
        before_artifact_digests=before,
        after_artifact_digests=after,
        checks=_checks(constraints),
        metrics=_metrics(visual, accessibility, interaction, constraints),
        evidence_levels=_evidence_levels(
            visual, accessibility, interaction, constraints
        ),
        rejection_reasons=reasons,
    )
    rehash_nested_artifacts(envelope)
    return envelope


def decode_verification_envelope(
    value: Mapping[str, Any] | Any,
) -> GuiVerificationReceiptEnvelope:
    """Decode a closed envelope mapping and require it to rehash."""

    payload = require_mapping(value, "GuiVerificationReceiptEnvelope")
    reject_unknown_fields(
        payload, _ENVELOPE_FIELDS, "GuiVerificationReceiptEnvelope"
    )
    required = (
        "application_id",
        "decision",
        "interface",
        "proposal_id",
        "receipt",
        "repository_revision",
        "schema_version",
        "screen_id",
        "verification_status",
    )
    missing = [name for name in required if name not in payload]
    if missing:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.MISSING_FIELD.value}: "
            f"missing {', '.join(missing)}"
        )
    if payload.get("interface") != GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE:
        raise GuiReceiptError("envelope interface is not GuiVerificationReceiptEnvelope@1")
    if payload.get("schema_version") != GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA:
        raise GuiReceiptError("unsupported verification receipt envelope schema")

    plan_raw = payload.get("invalidation_plan")
    plan = None if plan_raw in (None, "") else plan_raw
    envelope = aggregate_verification_receipts(
        visual_receipts=payload.get("visual_receipts", []),
        accessibility_receipts=payload.get("accessibility_receipts", []),
        interaction_receipts=payload.get("interaction_receipts", []),
        constraint_receipts=payload.get("constraint_receipts", []),
        decision=payload.get("decision", ""),
        proposal_id=payload.get("proposal_id", ""),
        application_id=payload.get("application_id", ""),
        screen_id=payload.get("screen_id", ""),
        repository_revision=payload.get("repository_revision", ""),
        invalidation_plan=plan,
        context_pack_id=payload.get("context_pack_id", ""),
        context_pack_digest=payload.get("context_pack_digest", ""),
        context_pack_cid=payload.get("context_pack_cid", ""),
        patch_digest=payload.get("patch_digest", ""),
        rejection_reasons=payload.get("rejection_reasons", []),
        receipt_id=payload.get("receipt", {}).get("receipt_id", "")
        if type(payload.get("receipt")) is dict
        else getattr(payload.get("receipt"), "receipt_id", ""),
        verification_status=payload.get("verification_status"),
        analysis_classification=payload.get("analysis_classification"),
        authority_ceiling=payload.get("authority_ceiling"),
    )
    claimed_digest = payload.get("envelope_digest", "")
    claimed_cid = payload.get("envelope_cid", "")
    if claimed_digest and claimed_digest != envelope.identity.digest:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
            "claimed envelope digest does not match"
        )
    if claimed_cid and claimed_cid != envelope.identity.cid:
        raise GuiReceiptError(
            f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
            "claimed envelope CID does not match"
        )
    claimed_receipt = payload.get("receipt")
    if claimed_receipt is not None:
        decoded_receipt = _decode_model(
            claimed_receipt, GuiImprovementReceipt, "receipt"
        )
        if decoded_receipt.to_dict() != envelope.receipt.to_dict():
            raise GuiReceiptError(
                f"{GuiReceiptIssueCode.IDENTITY_MISMATCH.value}: "
                "claimed improvement receipt does not match aggregation"
            )
    return envelope


class GuiVerificationReceiptAggregator:
    """Stateful facade for ``GuiVerificationReceiptAggregator@1``."""

    INTERFACE: Final = GUI_VERIFICATION_RECEIPT_AGGREGATOR_INTERFACE
    SCHEMA_VERSION: Final = GUI_VERIFICATION_RECEIPT_AGGREGATOR_SCHEMA
    VERSION: Final = GUI_VERIFICATION_RECEIPT_AGGREGATOR_VERSION

    def aggregate(self, **kwargs: Any) -> GuiVerificationReceiptEnvelope:
        return aggregate_verification_receipts(**kwargs)

    def identity_for(self, **kwargs: Any) -> GuiCanonicalIdentity:
        return self.aggregate(**kwargs).identity

    def decode(
        self, value: Mapping[str, Any] | Any
    ) -> GuiVerificationReceiptEnvelope:
        return decode_verification_envelope(value)

    def verify(
        self,
        envelope: GuiVerificationReceiptEnvelope,
        *,
        artifacts: Mapping[str, Any] | None = None,
    ) -> GuiVerificationReceiptEnvelope:
        return verify_envelope(envelope, artifacts=artifacts)


def create_verification_receipt_aggregator() -> GuiVerificationReceiptAggregator:
    """Factory for ``GuiVerificationReceiptAggregator@1``."""

    return GuiVerificationReceiptAggregator()


__all__ = [
    "ACCESSIBILITY_RECEIPT_INTERFACE",
    "CRITICAL_RECEIPT_INTERFACES",
    "DOMAIN_ACCESSIBILITY_RECEIPT",
    "DOMAIN_CONSTRAINT_RECEIPT",
    "DOMAIN_CONTEXT_PACK",
    "DOMAIN_IMPROVEMENT_RECEIPT",
    "DOMAIN_INTERACTION_RECEIPT",
    "DOMAIN_INVALIDATION_PLAN",
    "DOMAIN_PATCH",
    "DOMAIN_SCREENSHOT",
    "DOMAIN_VERIFICATION_ENVELOPE",
    "DOMAIN_VISUAL_REGRESSION_RECEIPT",
    "GUI_IMPROVEMENT_PROPOSAL_INTERFACE",
    "GUI_IMPROVEMENT_RECEIPT_INTERFACE",
    "GUI_VERIFICATION_RECEIPT_AGGREGATOR_INTERFACE",
    "GUI_VERIFICATION_RECEIPT_AGGREGATOR_SCHEMA",
    "GUI_VERIFICATION_RECEIPT_AGGREGATOR_VERSION",
    "GUI_VERIFICATION_RECEIPT_ENVELOPE_INTERFACE",
    "GUI_VERIFICATION_RECEIPT_ENVELOPE_SCHEMA",
    "INTERACTION_RECEIPT_INTERFACE",
    "UI_CONSTRAINT_RECEIPT_INTERFACE",
    "UI_CONTEXT_PACK_INTERFACE",
    "UI_INVALIDATION_PLAN_INTERFACE",
    "VERIFICATION_RECEIPT_INTERFACES",
    "VISUAL_REGRESSION_RECEIPT_INTERFACE",
    "GuiReceiptError",
    "GuiReceiptIssueCode",
    "GuiVerificationReceiptAggregator",
    "GuiVerificationReceiptEnvelope",
    "accessibility_receipt_identity",
    "aggregate_verification_receipts",
    "analysis_classification_for",
    "authority_ceiling_for",
    "bind_artifact_material",
    "constraint_receipt_identity",
    "create_verification_receipt_aggregator",
    "decode_verification_envelope",
    "envelope_identity",
    "improvement_receipt_identity",
    "interaction_receipt_identity",
    "receipt_identity",
    "rehash_nested_artifacts",
    "rehash_receipt_identity",
    "verify_envelope",
    "verify_receipt_identity",
    "visual_regression_receipt_identity",
]
