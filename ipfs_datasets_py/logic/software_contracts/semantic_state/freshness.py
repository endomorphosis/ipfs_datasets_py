"""Capsule freshness assessment separate from immutable capsules.

``CapsuleFreshness@1`` binds one capsule CID to the current state/view,
compiler/schema, producer identity, relevant binding projection, and any
applicable invalidation obligations.  Freshness is never a mutable capsule
field.

Admission rules (normative):

* Only a **fresh exact** capsule may substitute as ``exact_substitute``.
* Only a **fresh conservative** capsule with visible caveats may substitute as
  ``conservative_substitute_with_caveats``.
* Target/edit/test obligations, heuristic/opaque/stale/unknown/invalid inputs,
  schema/compiler mismatch, or missing capsule index binding all require raw
  source — no unsafe capsule may stand in for exact producer-bound source.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Final, Mapping, Protocol, Sequence, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    CAPSULE_COMPILER_VERSION,
    SEMANTIC_CAPSULE_SCHEMA,
    AdmissionDecision,
    CapsuleFreshness,
    FreshnessState,
    SemanticCapsule,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticStateModelError,
    SemanticStateRoot,
    SortedPairIndex,
)


# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------

CAPSULE_FRESHNESS_INTERFACE: Final[str] = "CapsuleFreshness@1"
CAPSULE_FRESHNESS_ASSESSOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-capsule-freshness-assessor@1"
)


class FreshnessError(ValueError):
    """Raised when freshness inputs fail closed verification."""


class FreshnessFailureKind(str, Enum):
    """Closed vocabulary for freshness assessment failure/rescan reasons."""

    INVALID_CAPSULE = "invalid_capsule"
    INVALID_STATE_VIEW = "invalid_state_view"
    MISSING_ROOT = "missing_root"
    SCHEMA_MISMATCH = "schema_mismatch"
    COMPILER_MISMATCH = "compiler_mismatch"
    PRODUCER_MISMATCH = "producer_mismatch"
    CAPSULE_INDEX_MISSING = "capsule_index_missing"
    CAPSULE_NOT_IN_INDEX = "capsule_not_in_index"
    CAPSULE_CID_MISMATCH = "capsule_cid_mismatch"
    CAPSULE_BLOCK_CORRUPT = "capsule_block_corrupt"
    BINDING_PROJECTION_MISMATCH = "binding_projection_mismatch"
    OBLIGATION_STALE = "obligation_stale"
    RAW_SOURCE_OBLIGATION = "raw_source_obligation"
    UNSAFE_CONFIDENCE = "unsafe_confidence"
    UNKNOWN_STATE = "unknown_state"


# Remediation kinds that force raw-source admission for a subject capsule.
_RAW_SOURCE_REMEDIATIONS: Final[frozenset[str]] = frozenset(
    {
        "retrieve_raw_source",
        "stale_bound_capsules",
        "rebuild_bound_artifacts",
        "rebuild_generated",
        "full_fallback",
        "full_pytest_fallback",
        "full_proofs_fallback",
    }
)

# Reason codes that mark the subject as edited/stale/unsafe for substitution.
_STALE_REASON_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "new_capsule",
        "raw_source_requirement",
        "deleted_symbol_dependency",
        "stale_bound_capsule",
        "caller_signature_mismatch",
        "obsolete_schema_adapter",
        "effect_assumption_stale",
        "exception_recovery_stale",
        "purity_security_review",
        "environment_receipt_stale",
        "stale_test_receipt",
        "full_fallback_required",
        "dependency_lock_changed",
        "dependency_manifest_changed",
        "pytest_config_changed",
        "pytest_plugin_changed",
        "proof_config_changed",
        "policy_changed",
        "interface_descriptor_changed",
        "generated_input_changed",
        "python_toolchain_changed",
        "semantic_schema_changed",
        "semantic_compiler_changed",
        "environment_binding_changed",
        "unknown_binding_scope",
        "unmapped_binding_subject",
    }
)


@runtime_checkable
class SemanticStateView(Protocol):
    """Read-only verified semantic-state view used for freshness assessment."""

    @property
    def root(self) -> SemanticStateRoot: ...

    def get_block(self, cid: str) -> bytes: ...


def _confidence_value(value: object) -> str:
    if isinstance(value, AnalysisConfidence):
        return value.value
    text = str(value)
    try:
        return AnalysisConfidence(text).value
    except ValueError:
        return text


def _require_capsule(capsule: object) -> SemanticCapsule:
    if not isinstance(capsule, SemanticCapsule):
        raise FreshnessError("capsule must be a SemanticCapsule")
    # Re-verify the capsule identity CID against its payload (fail closed).
    try:
        claimed = capsule.capsule_cid
        recomputed = decode_and_recompute_structured(
            claimed, capsule.identity_payload()
        )
    except Exception as exc:
        raise FreshnessError(
            f"{FreshnessFailureKind.INVALID_CAPSULE.value}: capsule does not reverify"
        ) from exc
    if recomputed != claimed:
        raise FreshnessError(
            f"{FreshnessFailureKind.INVALID_CAPSULE.value}: capsule_cid mismatch"
        )
    return capsule


def _require_view(view: object) -> tuple[SemanticStateRoot, object]:
    if not hasattr(view, "root") or not hasattr(view, "get_block"):
        raise FreshnessError(
            f"{FreshnessFailureKind.INVALID_STATE_VIEW.value}: "
            "current_state must provide root and get_block"
        )
    root = view.root  # type: ignore[attr-defined]
    if not isinstance(root, SemanticStateRoot):
        raise FreshnessError(
            f"{FreshnessFailureKind.MISSING_ROOT.value}: "
            "current_state.root must be a SemanticStateRoot"
        )
    return root, view


def _load_capsule_index(view: object, root: SemanticStateRoot) -> SortedPairIndex | None:
    """Load and reverify the capsule index, or return None when unavailable."""
    cid = root.capsule_index_cid
    try:
        data = view.get_block(cid)  # type: ignore[attr-defined]
    except Exception:
        return None
    if type(data) is not bytes:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
        if type(payload) is not dict:
            return None
        # Blocks store identity_payload (no index_cid); to_dict form is also accepted.
        identity = {
            key: value
            for key, value in payload.items()
            if key != "index_cid"
        }
        if "index_cid" not in payload and canonical_dag_json_bytes(identity) != data:
            return None
        decode_and_recompute_structured(cid, identity)
        return SortedPairIndex.from_dict({**identity, "index_cid": cid})
    except Exception:
        return None


def _lookup_index_cid(
    index: SortedPairIndex | None, stable_symbol_id: str
) -> str | None:
    if index is None:
        return None
    for key, value in index.pairs:
        if key == stable_symbol_id:
            return value
    return None


def _load_and_verify_capsule_block(
    view: object, claimed_cid: str, expected: SemanticCapsule
) -> tuple[bool, list[str]]:
    """Reverify the stored capsule block against the assessment candidate.

    Returns ``(matched, caveats)``.  Missing/corrupt blocks yield caveats and
    ``matched=False`` without raising — the assessor fails closed into raw
    source rather than crashing on optional index presence.
    """
    caveats: list[str] = []
    try:
        data = view.get_block(claimed_cid)  # type: ignore[attr-defined]
    except Exception:
        caveats.append(FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value)
        return False, caveats
    if type(data) is not bytes:
        caveats.append(FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value)
        return False, caveats
    try:
        payload = json.loads(data.decode("utf-8"))
        if type(payload) is not dict:
            caveats.append(FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value)
            return False, caveats
        identity = {
            key: value for key, value in payload.items() if key != "capsule_cid"
        }
        decode_and_recompute_structured(claimed_cid, identity)
        stored = SemanticCapsule.from_dict({**identity, "capsule_cid": claimed_cid})
        if stored.capsule_cid != expected.capsule_cid:
            caveats.append(FreshnessFailureKind.CAPSULE_CID_MISMATCH.value)
            return False, caveats
        if stored.identity_payload() != expected.identity_payload():
            caveats.append(FreshnessFailureKind.CAPSULE_CID_MISMATCH.value)
            return False, caveats
        return True, caveats
    except Exception:
        caveats.append(FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value)
        return False, caveats


def _applicable_obligations(
    capsule: SemanticCapsule,
    invalidation: SemanticInvalidationPlan | None,
) -> tuple[tuple[SemanticInvalidationObligation, ...], list[str], bool, bool]:
    """Return (obligations, caveats, is_stale, raw_source_forced)."""
    if invalidation is None:
        return (), [], False, False
    if not isinstance(invalidation, SemanticInvalidationPlan):
        raise FreshnessError("invalidation must be a SemanticInvalidationPlan or None")

    subject = capsule.stable_symbol_id
    dep_ids = frozenset(capsule.dependency_stable_ids)
    selected: list[SemanticInvalidationObligation] = []
    caveats: list[str] = []
    is_stale = False
    raw_forced = False

    for obligation in invalidation.obligations:
        if not isinstance(obligation, SemanticInvalidationObligation):
            raise FreshnessError(
                "invalidation.obligations must be SemanticInvalidationObligation values"
            )
        reason = str(obligation.reason_code)
        remediation = str(obligation.remediation_kind)
        subj = obligation.subject_id
        touches = (
            subj == subject
            or subj in dep_ids
            or subj == capsule.source_slice_path
            or (capsule.source_cid is not None and subj == capsule.source_cid)
        )
        if not touches:
            # Global/full-fallback obligations still force raw source.
            if remediation in {
                "full_fallback",
                "full_pytest_fallback",
                "full_proofs_fallback",
            } or reason in {"full_fallback_required", "unknown_binding_scope"}:
                touches = True
            else:
                continue
        selected.append(obligation)
        if remediation in _RAW_SOURCE_REMEDIATIONS or reason in {
            "raw_source_requirement",
            "new_capsule",
            "deleted_symbol_dependency",
        }:
            raw_forced = True
            caveats.append(f"obligation:{reason}")
        if reason in _STALE_REASON_MARKERS or remediation in _RAW_SOURCE_REMEDIATIONS:
            is_stale = True
            if f"obligation:{reason}" not in caveats:
                caveats.append(f"obligation:{reason}")

    # Deterministic order already enforced by plan; re-sort by obligation_id.
    selected_sorted = tuple(sorted(selected, key=lambda item: item.obligation_id))
    return selected_sorted, caveats, is_stale, raw_forced


def assess_capsule_freshness(
    capsule: SemanticCapsule,
    *,
    current_state: SemanticStateView,
    invalidation: SemanticInvalidationPlan | None = None,
) -> CapsuleFreshness:
    """Assess whether ``capsule`` may substitute under ``current_state``.

    Returns a durable :class:`CapsuleFreshness` record.  Assessment never mutates
    the capsule.  Unsafe, stale, unknown, or obligation-invalidated capsules
    always admit ``raw_source_required`` so exact producer-bound source must be
    retrieved instead.
    """
    capsule = _require_capsule(capsule)
    root, view = _require_view(current_state)

    caveats: list[str] = []
    freshness = FreshnessState.FRESH
    admission = AdmissionDecision.RAW_SOURCE_REQUIRED

    # Schema / compiler must match the current root contract.
    if capsule.capsule_schema != root.capsule_schema:
        freshness = FreshnessState.UNKNOWN
        caveats.append(FreshnessFailureKind.SCHEMA_MISMATCH.value)
    elif capsule.capsule_schema != SEMANTIC_CAPSULE_SCHEMA:
        freshness = FreshnessState.UNKNOWN
        caveats.append(FreshnessFailureKind.SCHEMA_MISMATCH.value)

    if capsule.capsule_compiler_version != root.capsule_compiler_version:
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.COMPILER_MISMATCH.value)
    elif capsule.capsule_compiler_version != CAPSULE_COMPILER_VERSION:
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.COMPILER_MISMATCH.value)

    # Producer identity is taken from the current root (assessment binding).
    producer_state_cid = root.producer.repository_state_cid
    if capsule.semantic_index_schema != root.producer.semantic_index_schema:
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.PRODUCER_MISMATCH.value)
    if capsule.extractor_version != root.producer.extractor_version:
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.PRODUCER_MISMATCH.value)

    # Verify capsule is still the current index binding when the index is present.
    index = _load_capsule_index(view, root)
    index_cid = _lookup_index_cid(index, capsule.stable_symbol_id)
    if index is None:
        # Missing index does not invent freshness; mark unknown unless already stale.
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.UNKNOWN
        caveats.append(FreshnessFailureKind.CAPSULE_INDEX_MISSING.value)
    elif index_cid is None:
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.CAPSULE_NOT_IN_INDEX.value)
    elif index_cid != capsule.capsule_cid:
        freshness = FreshnessState.STALE
        caveats.append(FreshnessFailureKind.CAPSULE_CID_MISMATCH.value)
    else:
        matched, block_caveats = _load_and_verify_capsule_block(
            view, index_cid, capsule
        )
        caveats.extend(block_caveats)
        if not matched:
            freshness = FreshnessState.STALE

    # Binding projection CID is already part of capsule identity.  When the
    # view also stores the projection block, reverify it; absence is fine.
    projection_cid = capsule.relevant_binding_projection_cid
    if projection_cid is not None:
        try:
            pdata = view.get_block(projection_cid)  # type: ignore[attr-defined]
        except Exception:
            pdata = None
        if pdata is not None:
            try:
                if type(pdata) is not bytes:
                    raise FreshnessError("projection block must be bytes")
                payload = json.loads(pdata.decode("utf-8"))
                identity = {
                    key: value
                    for key, value in payload.items()
                    if key != "projection_cid"
                }
                decode_and_recompute_structured(projection_cid, identity)
            except Exception:
                if freshness == FreshnessState.FRESH:
                    freshness = FreshnessState.UNKNOWN
                caveats.append(FreshnessFailureKind.BINDING_PROJECTION_MISMATCH.value)

    # Invalidation obligations.
    applicable, obl_caveats, is_stale, raw_forced = _applicable_obligations(
        capsule, invalidation
    )
    caveats.extend(obl_caveats)
    if is_stale:
        freshness = FreshnessState.STALE
    if raw_forced:
        admission = AdmissionDecision.RAW_SOURCE_REQUIRED

    # Confidence gate: heuristic/opaque never substitute for raw source.
    confidence = _confidence_value(capsule.confidence)
    if confidence in {
        AnalysisConfidence.HEURISTIC.value,
        AnalysisConfidence.OPAQUE.value,
    }:
        caveats.append(f"{FreshnessFailureKind.UNSAFE_CONFIDENCE.value}:{confidence}")
        admission = AdmissionDecision.RAW_SOURCE_REQUIRED
    elif confidence not in {
        AnalysisConfidence.EXACT.value,
        AnalysisConfidence.CONSERVATIVE.value,
    }:
        caveats.append(f"{FreshnessFailureKind.UNSAFE_CONFIDENCE.value}:{confidence}")
        if freshness == FreshnessState.FRESH:
            freshness = FreshnessState.UNKNOWN
        admission = AdmissionDecision.RAW_SOURCE_REQUIRED

    # Admission decision when not already forced to raw source by obligations
    # or unsafe confidence.
    blocking = {
        FreshnessFailureKind.SCHEMA_MISMATCH.value,
        FreshnessFailureKind.COMPILER_MISMATCH.value,
        FreshnessFailureKind.PRODUCER_MISMATCH.value,
        FreshnessFailureKind.CAPSULE_NOT_IN_INDEX.value,
        FreshnessFailureKind.CAPSULE_CID_MISMATCH.value,
        FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value,
        FreshnessFailureKind.BINDING_PROJECTION_MISMATCH.value,
        FreshnessFailureKind.CAPSULE_INDEX_MISSING.value,
    }
    blocked = any(
        c in blocking or c.startswith(FreshnessFailureKind.UNSAFE_CONFIDENCE.value)
        for c in caveats
    ) or raw_forced or freshness in {FreshnessState.STALE, FreshnessState.UNKNOWN}

    if not blocked and freshness == FreshnessState.FRESH:
        if confidence == AnalysisConfidence.EXACT.value:
            admission = AdmissionDecision.EXACT_SUBSTITUTE
        elif confidence == AnalysisConfidence.CONSERVATIVE.value:
            admission = AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS
            caveats.append("confidence:conservative")
        else:
            admission = AdmissionDecision.RAW_SOURCE_REQUIRED
    else:
        admission = AdmissionDecision.RAW_SOURCE_REQUIRED
        if freshness == FreshnessState.FRESH and blocked:
            # Confidence-only blocks keep freshness "fresh" only when the capsule
            # itself is current; unsafe confidence is still non-substitutable.
            if any(
                c.startswith(FreshnessFailureKind.UNSAFE_CONFIDENCE.value)
                for c in caveats
            ) and not any(c in blocking for c in caveats) and not is_stale:
                freshness = FreshnessState.FRESH
            elif FreshnessFailureKind.CAPSULE_INDEX_MISSING.value in caveats and not is_stale:
                freshness = FreshnessState.UNKNOWN
            elif is_stale:
                freshness = FreshnessState.STALE

    # Unique, sorted caveats (CapsuleFreshness enforces uniqueness).
    unique_caveats = tuple(sorted(set(caveats)))
    obligation_ids = tuple(item.obligation_id for item in applicable)

    try:
        return CapsuleFreshness(
            capsule_cid=capsule.capsule_cid,
            root_cid=root.root_cid,
            capsule_schema=capsule.capsule_schema,
            capsule_compiler_version=capsule.capsule_compiler_version,
            producer_repository_state_cid=producer_state_cid,
            relevant_binding_projection_cid=projection_cid,
            freshness=freshness,
            admission=admission,
            applicable_obligation_ids=obligation_ids,
            caveats=unique_caveats,
        )
    except SemanticStateModelError as exc:
        raise FreshnessError(f"CapsuleFreshness construction failed: {exc}") from exc


def requires_raw_source(assessment: CapsuleFreshness) -> bool:
    """Return True when ``assessment`` forbids capsule substitution."""
    if not isinstance(assessment, CapsuleFreshness):
        raise FreshnessError("assessment must be a CapsuleFreshness")
    return str(assessment.admission) == AdmissionDecision.RAW_SOURCE_REQUIRED.value


def is_safe_substitute(assessment: CapsuleFreshness) -> bool:
    """Return True only for fresh exact or visibly caveated conservative admission."""
    if not isinstance(assessment, CapsuleFreshness):
        raise FreshnessError("assessment must be a CapsuleFreshness")
    if str(assessment.freshness) != FreshnessState.FRESH.value:
        return False
    admission = str(assessment.admission)
    if admission == AdmissionDecision.EXACT_SUBSTITUTE.value:
        return True
    if admission == AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS.value:
        # Conservative substitutes must carry at least one visible caveat.
        return bool(assessment.caveats)
    return False


__all__ = [
    "CAPSULE_FRESHNESS_ASSESSOR_SCHEMA",
    "CAPSULE_FRESHNESS_INTERFACE",
    "FreshnessError",
    "FreshnessFailureKind",
    "SemanticStateView",
    "assess_capsule_freshness",
    "is_safe_substitute",
    "requires_raw_source",
]
