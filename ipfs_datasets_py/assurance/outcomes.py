"""FACP-023: Replace Datasets false-success fallbacks with FCA outcomes.

Download, upload, pin/get/save, and semantic-result surfaces must return typed
closed Formal Claim Algebra (FCA) outcomes. Missing backends or dependencies
yield ``Unavailable``. An attempt without an independent effect observation is
``Attempted`` / ``Unknown`` — never success. ``Verified`` requires admitted
current-verifier evidence. Compatibility projection of legacy
``status=success`` stubs preserves non-success disposition.

Cold import is hermetic: no network, installer, or process mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal, Mapping, Optional

TASK_ID: Final[str] = "FACP-023"
GOAL_ID: Final[str] = "FACP-G210"
BUNDLE: Final[str] = "facp/migration/datasets-outcomes"
EVIDENCE_ID: Final[str] = "facp/datasets-outcomes@1"
INTERFACE: Final[str] = "DatasetsFormalClaimOutcomes@1"
FCA_VOCABULARY_SCHEMA: Final[str] = "facp/formal-claim-algebra-v1@1"
UNSAFE_PROMOTION: Final[bool] = False

ClosedOutcome = Literal[
    "Unavailable",
    "Rejected",
    "Simulated",
    "Attempted",
    "Unknown",
    "Observed",
    "Verified",
    "Failed",
    "Compensated",
]

OperationKind = Literal[
    "download",
    "upload",
    "pin",
    "get",
    "save",
    "semantic",
    "cluster",
    "backend_add",
]

CLOSED_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "Unavailable",
        "Rejected",
        "Simulated",
        "Attempted",
        "Unknown",
        "Observed",
        "Verified",
        "Failed",
        "Compensated",
    }
)

# Outcomes that may ever report success disposition (ok=True).
_SUCCESS_OUTCOMES: Final[frozenset[str]] = frozenset({"Observed", "Verified"})

# Codes that pair with Observed/Verified for ok=True.
_SUCCESS_CODES: Final[frozenset[str]] = frozenset(
    {
        "effect_observed",
        "verified_admitted",
        "download_observed",
        "upload_observed",
        "semantic_observed",
        "pin_observed",
        "get_observed",
        "save_observed",
    }
)

# Inventoried false-success families (FACP-003 / datasets_claims.json).
INVENTORIED_FALSE_SUCCESS_FAMILIES: Final[tuple[str, ...]] = (
    "download_fallback_stub_success",
    "download_placeholder_success",
    "upload_placeholder_success",
    "upload_mock_cid_success",
    "download_mock_content_success",
    "cluster_upload_download_mock_success",
    "dataset_tool_mock_save_success",
    "simulated_upload_cid",
    "semantic_result_simulated_success",
)

INVENTORY_DEFECT_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "download_fallback_stub_success": "DS-FALSE-001",
        "download_placeholder_success": "DS-FALSE-002",
        "upload_placeholder_success": "DS-FALSE-003",
        "upload_mock_cid_success": "DS-FALSE-004",
        "download_mock_content_success": "DS-FALSE-005",
        "cluster_upload_download_mock_success": "DS-FALSE-006",
        "dataset_tool_mock_save_success": "DS-FALSE-007",
        "simulated_upload_cid": "DS-FALSE-008",
        "semantic_result_simulated_success": "DS-FALSE-009",
    }
)

# Evidence keys required to admit Verified (aligned with proof_reusable +
# effect_successful necessary_evidence from facp/promotion-rules@1).
VERIFIER_ADMISSION_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "named_current_verifier",
        "verifier_admission_closure",
    }
)
EFFECT_OBSERVATION_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "independent_effect_observation",
        "admission_token",
    }
)
VERIFIED_REQUIRED_EVIDENCE: Final[frozenset[str]] = (
    VERIFIER_ADMISSION_EVIDENCE | EFFECT_OBSERVATION_EVIDENCE
)

_WEAK_ORIGINS: Final[frozenset[str]] = frozenset(
    {"absent", "declared", "fixture", "simulated"}
)
_OBSERVABLE_ORIGINS: Final[frozenset[str]] = frozenset(
    {"hermetic_observed", "live_observed"}
)
_VALID_INTEGRITY: Final[frozenset[str]] = frozenset(
    {"digest_valid", "signature_valid"}
)
_ALLOWED_POLICY: Final[frozenset[str]] = frozenset(
    {"allowed", "allowed_with_obligations"}
)

FORBIDDEN_LEGACY_SUCCESS_FIELDS: Final[frozenset[str]] = frozenset(
    {"success", "ok", "passed", "production_supported"}
)

DIMENSION_ORDER: Final[tuple[str, ...]] = (
    "origin",
    "integrity",
    "authority",
    "policy",
    "proof",
    "freshness",
    "effect",
    "environment",
    "review",
)


class DatasetOutcomeError(ValueError):
    """Malformed Datasets FCA outcome construction."""


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Nine-dimension FCA evidence product (weakest defaults)."""

    origin: str = "absent"
    integrity: str = "unchecked"
    authority: str = "unchecked"
    policy: str = "unchecked"
    proof: str = "none"
    freshness: str = "stale"
    effect: str = "not_started"
    environment: str = "hermetic"
    review: str = "unreviewed"

    def to_mapping(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in DIMENSION_ORDER}

    def with_overrides(self, **overrides: str) -> "EvidenceEnvelope":
        data = self.to_mapping()
        data.update(overrides)
        return EvidenceEnvelope(**data)


@dataclass(frozen=True)
class DatasetOutcome:
    """Typed closed-outcome result for a Datasets effectful operation.

    ``ok`` is true only for Observed/Verified with an admitted success code.
    Attempted, Unavailable, Simulated, Unknown, Failed, and Rejected are never
    success dispositions — including when a legacy caller expected
    ``status=success``.
    """

    outcome: ClosedOutcome
    code: str
    message: str
    operation: OperationKind | str
    envelope: EvidenceEnvelope = field(default_factory=EvidenceEnvelope)
    evidence: frozenset[str] = field(default_factory=frozenset)
    defect_family: str | None = None
    defect_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    unsafe_promotion: bool = False

    def __post_init__(self) -> None:
        if self.outcome not in CLOSED_OUTCOMES:
            raise DatasetOutcomeError(f"unknown closed outcome: {self.outcome!r}")
        if self.unsafe_promotion:
            raise DatasetOutcomeError(
                "unsafe_promotion must remain False on Datasets outcomes"
            )
        # Freeze details mapping.
        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(self.details)),
        )
        object.__setattr__(self, "evidence", frozenset(self.evidence))

    @property
    def ok(self) -> bool:
        """True only for observed/verified success — never for Attempted."""
        return self.outcome in _SUCCESS_OUTCOMES and self.code in _SUCCESS_CODES

    @property
    def is_success_disposition(self) -> bool:
        """Alias used by compatibility projection checks."""
        return self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "code": self.code,
            "message": self.message,
            "operation": self.operation,
            "ok": self.ok,
            "envelope": self.envelope.to_mapping(),
            "evidence": sorted(self.evidence),
            "defect_family": self.defect_family,
            "defect_id": self.defect_id,
            "details": dict(self.details),
            "unsafe_promotion": self.unsafe_promotion,
            "task_id": TASK_ID,
            "evidence_id": EVIDENCE_ID,
            "fca_vocabulary_schema": FCA_VOCABULARY_SCHEMA,
        }

    def to_legacy_compat_dict(self) -> dict[str, Any]:
        """Project to a dict-shaped compatibility surface.

        Never emits ``status=success`` / ``success=True`` for non-success
        dispositions. Preserves typed outcome fields for honest consumers.
        """
        payload = {
            "status": "success" if self.ok else self.outcome.lower(),
            "outcome": self.outcome,
            "code": self.code,
            "message": self.message,
            "operation": self.operation,
            "ok": self.ok,
            "disposition": "success" if self.ok else "non_success",
        }
        # Carry selected details without inventing durable effects.
        for key in ("backend", "dependency", "cid", "dataset", "content"):
            if key in self.details:
                payload[key] = self.details[key]
        if self.defect_family is not None:
            payload["defect_family"] = self.defect_family
        if self.defect_id is not None:
            payload["defect_id"] = self.defect_id
        return payload


def _family_meta(family: str) -> tuple[str, str]:
    if family not in INVENTORY_DEFECT_IDS:
        raise DatasetOutcomeError(f"unknown inventoried family: {family!r}")
    return family, INVENTORY_DEFECT_IDS[family]


def unavailable_missing_backend(
    *,
    operation: OperationKind | str,
    backend: str | None = None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Missing backend → typed Unavailable (never success)."""
    return DatasetOutcome(
        outcome="Unavailable",
        code="backend_unavailable",
        message=message
        or f"backend {backend!r} is unavailable for operation {operation!r}",
        operation=operation,
        envelope=EvidenceEnvelope(effect="not_started", origin="absent"),
        details={
            "backend": backend,
            "fallback_success_forbidden": True,
            **dict(details or {}),
        },
    )


def unavailable_missing_dependency(
    *,
    operation: OperationKind | str,
    dependency: str,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Missing dependency → typed Unavailable (never success)."""
    return DatasetOutcome(
        outcome="Unavailable",
        code="dependency_unavailable",
        message=message
        or f"required dependency {dependency!r} is not available for {operation!r}",
        operation=operation,
        envelope=EvidenceEnvelope(effect="not_started", origin="absent"),
        details={
            "dependency": dependency,
            "fallback_success_forbidden": True,
            **dict(details or {}),
        },
    )


def begin_attempt(
    *,
    operation: OperationKind | str,
    origin: str = "declared",
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Record that an effectful operation was attempted but not yet observed.

    Attempted-but-unobserved is explicitly not a success disposition.
    """
    if origin in _WEAK_ORIGINS or origin == "hermetic_observed":
        env_origin = origin
    else:
        env_origin = "declared"
    return DatasetOutcome(
        outcome="Attempted",
        code="effect_attempted",
        message=f"operation {operation!r} started; independent observation pending",
        operation=operation,
        envelope=EvidenceEnvelope(effect="started", origin=env_origin),
        evidence=frozenset(),
        details={"attempt_evidenced": True, **dict(details or {})},
    )


def bind_effect_observation(
    attempt: DatasetOutcome,
    *,
    observation_present: bool,
    observation_id: str | None = None,
    admission_token: str | None = None,
    origin: str = "hermetic_observed",
    integrity: str = "digest_valid",
    authority: str = "valid",
    policy: str = "allowed",
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Bind an independent effect observation to a prior attempt.

    Without observation evidence the result remains non-success (Unknown).
    Observation alone yields Observed — Verified requires separate admission.
    """
    if attempt.outcome not in {"Attempted", "Unknown", "Observed"}:
        return DatasetOutcome(
            outcome="Failed",
            code="observation_requires_attempt",
            message=(
                "bind_effect_observation requires a prior Attempted/Unknown/"
                f"Observed outcome, got {attempt.outcome!r}"
            ),
            operation=attempt.operation,
            envelope=attempt.envelope,
            evidence=attempt.evidence,
            details={"prior_outcome": attempt.outcome, **dict(details or {})},
        )

    if not observation_present or not observation_id:
        return DatasetOutcome(
            outcome="Unknown",
            code="attempted_unobserved",
            message=(
                f"operation {attempt.operation!r} was attempted but no independent "
                "effect observation is available; not success"
            ),
            operation=attempt.operation,
            envelope=attempt.envelope.with_overrides(effect="externally_unknown"),
            evidence=attempt.evidence,
            details={
                "attempt_evidenced": True,
                "observation_present": False,
                "success_forbidden_without_observation": True,
                **dict(details or {}),
            },
        )

    if origin not in _OBSERVABLE_ORIGINS:
        return DatasetOutcome(
            outcome="Failed",
            code="weak_origin_cannot_observe",
            message=f"origin {origin!r} cannot bind an effect observation",
            operation=attempt.operation,
            envelope=attempt.envelope.with_overrides(origin=origin, effect="started"),
            evidence=attempt.evidence,
            details={"origin": origin, **dict(details or {})},
        )

    evidence = set(attempt.evidence)
    evidence.add("independent_effect_observation")
    if admission_token:
        evidence.add("admission_token")

    # effect_successful also needs admission_token; without it stay Observed
    # only when admission_token is present — otherwise Observed with incomplete
    # bag is still ok for Observed code, but Verified admission will reject.
    code = f"{attempt.operation}_observed" if attempt.operation in {
        "download",
        "upload",
        "semantic",
        "pin",
        "get",
        "save",
    } else "effect_observed"
    # Normalize unknown operation kinds to generic success code.
    if code not in _SUCCESS_CODES:
        code = "effect_observed"

    return DatasetOutcome(
        outcome="Observed",
        code=code,
        message=f"operation {attempt.operation!r} observed via independent evidence",
        operation=attempt.operation,
        envelope=EvidenceEnvelope(
            origin=origin,
            integrity=integrity if integrity in _VALID_INTEGRITY else "unchecked",
            authority=authority if authority == "valid" else "unchecked",
            policy=policy if policy in _ALLOWED_POLICY else "unchecked",
            proof="none",
            freshness="current",
            effect="observed",
            environment="hermetic" if origin == "hermetic_observed" else "live",
            review="machine_reviewed",
        ),
        evidence=frozenset(evidence),
        details={
            "observation_id": observation_id,
            "admission_token": admission_token,
            **dict(details or {}),
        },
    )


def admit_verified(
    observed: DatasetOutcome,
    *,
    verifier_evidence: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Promote Observed → Verified only with admitted current-verifier evidence.

    Requires:
    * prior outcome Observed with ``effect.observed``
    * non-weak origin
    * ``named_current_verifier`` and ``verifier_admission_closure``
    * ``independent_effect_observation`` and ``admission_token``
    * ``proof`` admitted as verified under current freshness
    """
    bag = dict(verifier_evidence or {})
    present_keys = {
        key for key, value in bag.items() if value not in (None, False, "", [])
    }
    present_keys |= set(observed.evidence)

    missing = sorted(VERIFIED_REQUIRED_EVIDENCE - present_keys)
    if observed.outcome != "Observed":
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_requires_observed",
            message="Verified requires a prior Observed outcome",
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details={
                "prior_outcome": observed.outcome,
                "missing_evidence": missing,
                **dict(details or {}),
            },
        )

    if observed.envelope.effect != "observed":
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_requires_effect_observed",
            message="Verified requires envelope.effect == 'observed'",
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details={"missing_evidence": missing, **dict(details or {})},
        )

    if observed.envelope.origin in _WEAK_ORIGINS:
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_rejects_weak_origin",
            message=f"origin {observed.envelope.origin!r} cannot admit Verified",
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details={"missing_evidence": missing, **dict(details or {})},
        )

    if missing:
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_missing_admitted_verifier_evidence",
            message=(
                "Verified requires admitted verifier evidence: "
                + ", ".join(sorted(VERIFIED_REQUIRED_EVIDENCE))
            ),
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details={
                "missing_evidence": missing,
                "required_evidence": sorted(VERIFIED_REQUIRED_EVIDENCE),
                **dict(details or {}),
            },
        )

    # Proof dimension must be admitted as verified (not merely candidate).
    # Presence of named_current_verifier + verifier_admission_closure (already
    # checked via VERIFIED_REQUIRED_EVIDENCE) is the admission gate; an
    # explicit proof_role/proof value may only narrow, never widen.
    proof_role = str(bag.get("proof_role") or bag.get("proof") or "verified")
    if proof_role in {"none", "candidate", "refuted", "unknown", "verifier_unavailable"}:
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_requires_admitted_proof",
            message="Verified rejects non-admitted proof roles (candidate/none/…)",
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details={"proof_role": proof_role, **dict(details or {})},
        )

    if observed.envelope.integrity not in _VALID_INTEGRITY:
        return DatasetOutcome(
            outcome="Rejected",
            code="verified_requires_valid_integrity",
            message="Verified requires digest_valid or signature_valid integrity",
            operation=observed.operation,
            envelope=observed.envelope,
            evidence=frozenset(present_keys),
            details=dict(details or {}),
        )

    return DatasetOutcome(
        outcome="Verified",
        code="verified_admitted",
        message=f"operation {observed.operation!r} verified under admitted verifier",
        operation=observed.operation,
        envelope=observed.envelope.with_overrides(
            proof="verified",
            freshness="current",
        ),
        evidence=frozenset(present_keys),
        details={
            "verifier": bag.get("named_current_verifier"),
            "proof_role": proof_role or "verified",
            **dict(details or {}),
        },
    )


def project_compatibility(
    legacy: Mapping[str, Any],
    *,
    operation: OperationKind | str | None = None,
    defect_family: str | None = None,
) -> DatasetOutcome:
    """Conservatively project a legacy Datasets result onto an FCA outcome.

    Compatibility projection **preserves non-success disposition**: a legacy
    ``status=success`` / ``success=True`` stub without durable effect
    observation never becomes Observed/Verified. Simulated/mock origins map to
    ``Simulated``. Missing backends map to ``Unavailable``.
    """
    op = str(
        operation
        or legacy.get("operation")
        or legacy.get("op")
        or "download"
    )
    family = defect_family or legacy.get("defect_family")
    defect_id: str | None = None
    if isinstance(family, str) and family in INVENTORY_DEFECT_IDS:
        defect_id = INVENTORY_DEFECT_IDS[family]

    details: dict[str, Any] = {
        "legacy_keys": sorted(str(k) for k in legacy.keys()),
        "compatibility_projection": True,
    }
    if family:
        details["defect_family"] = family
    if defect_id:
        details["defect_id"] = defect_id

    # Explicit mock / simulated markers.
    note = str(legacy.get("note") or legacy.get("message") or "").lower()
    mockish = (
        legacy.get("mock") is True
        or legacy.get("simulated") is True
        or "mock" in note
        or "simulated" in note
        or str(legacy.get("origin") or "").lower() in {"mock", "simulated", "fixture"}
        or (
            isinstance(legacy.get("cid"), str)
            and str(legacy.get("cid")).startswith("Qm")
            and legacy.get("durable_effect") is False
        )
        or (
            isinstance(legacy.get("content"), str)
            and str(legacy.get("content")).startswith("Mock content")
        )
        or (
            isinstance(legacy.get("dataset_id"), str)
            and str(legacy.get("dataset_id")).startswith("mock_")
        )
    )

    status = legacy.get("status")
    success_flag = legacy.get("success")
    claims_success = (
        status == "success"
        or success_flag is True
        or any(legacy.get(k) is True for k in FORBIDDEN_LEGACY_SUCCESS_FIELDS)
    )

    attempt_evidenced = legacy.get("attempt_evidenced") is True
    observation_present = (
        legacy.get("independent_effect_observation") is True
        or legacy.get("observation_present") is True
        or legacy.get("durable_effect") is True
    )

    if legacy.get("backend_available") is False or legacy.get("dependency_available") is False:
        code = (
            "backend_unavailable"
            if legacy.get("backend_available") is False
            else "dependency_unavailable"
        )
        return DatasetOutcome(
            outcome="Unavailable",
            code=code,
            message="compatibility projection: missing backend/dependency is Unavailable",
            operation=op,
            envelope=EvidenceEnvelope(effect="not_started", origin="absent"),
            defect_family=str(family) if family else None,
            defect_id=defect_id,
            details={**details, "claims_success_clamped": bool(claims_success)},
        )

    if mockish and claims_success:
        return DatasetOutcome(
            outcome="Simulated",
            code="legacy_simulated_success_clamped",
            message=(
                "compatibility projection: simulated/mock success is Simulated, "
                "not Observed/Verified"
            ),
            operation=op,
            envelope=EvidenceEnvelope(
                origin="simulated",
                effect="started" if attempt_evidenced else "not_started",
            ),
            defect_family=str(family) if family else None,
            defect_id=defect_id,
            details={**details, "claims_success_clamped": True},
        )

    if claims_success and not observation_present:
        if attempt_evidenced:
            return DatasetOutcome(
                outcome="Attempted",
                code="legacy_success_without_observation",
                message=(
                    "compatibility projection: legacy success without observation "
                    "is Attempted, not success"
                ),
                operation=op,
                envelope=EvidenceEnvelope(effect="started", origin="declared"),
                defect_family=str(family) if family else None,
                defect_id=defect_id,
                details={**details, "claims_success_clamped": True},
            )
        return DatasetOutcome(
            outcome="Unavailable",
            code="legacy_success_without_effect",
            message=(
                "compatibility projection: legacy status=success without durable "
                "effect is Unavailable"
            ),
            operation=op,
            envelope=EvidenceEnvelope(effect="not_started", origin="absent"),
            defect_family=str(family) if family else None,
            defect_id=defect_id,
            details={**details, "claims_success_clamped": True},
        )

    if status == "error" or success_flag is False:
        return DatasetOutcome(
            outcome="Failed",
            code="legacy_explicit_failure",
            message="compatibility projection: legacy failure retained as Failed",
            operation=op,
            envelope=EvidenceEnvelope(effect="failed", origin="declared"),
            defect_family=str(family) if family else None,
            defect_id=defect_id,
            details=details,
        )

    if claims_success and observation_present:
        # Still do not auto-upgrade to Verified; Observed only when observation
        # evidence is explicitly present AND origin is observable.
        return DatasetOutcome(
            outcome="Observed",
            code="effect_observed",
            message="compatibility projection: observation-backed legacy success",
            operation=op,
            envelope=EvidenceEnvelope(
                origin="hermetic_observed",
                integrity="digest_valid",
                authority="valid",
                policy="allowed",
                effect="observed",
                freshness="current",
            ),
            evidence=frozenset({"independent_effect_observation", "admission_token"}),
            defect_family=str(family) if family else None,
            defect_id=defect_id,
            details=details,
        )

    return DatasetOutcome(
        outcome="Unavailable",
        code="legacy_unclassified_non_success",
        message="compatibility projection: unclassified legacy result is Unavailable",
        operation=op,
        envelope=EvidenceEnvelope(),
        defect_family=str(family) if family else None,
        defect_id=defect_id,
        details=details,
    )


def replace_false_success_fallback(
    *,
    family: str,
    operation: OperationKind | str | None = None,
    backend_available: bool = False,
    dependency_available: bool = True,
    attempt_evidenced: bool = False,
    observation_present: bool = False,
    simulated: bool = False,
    legacy: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Replace an inventoried false-success fallback with a typed outcome.

    This is the migration adapter surface for bounded download/upload/semantic
    call sites inventoried under FACP-003. Production call sites must invoke
    this (or the finer helpers) instead of returning ``status=success`` stubs.
    """
    family_name, defect_id = _family_meta(family)
    op = operation or _default_operation_for_family(family_name)

    def _annotate(out: DatasetOutcome) -> DatasetOutcome:
        return DatasetOutcome(
            outcome=out.outcome,
            code=out.code,
            message=out.message,
            operation=out.operation,
            envelope=out.envelope,
            evidence=out.evidence,
            defect_family=family_name,
            defect_id=defect_id,
            details={
                **dict(out.details),
                "defect_family": family_name,
                "defect_id": defect_id,
            },
        )

    if not dependency_available:
        return _annotate(
            unavailable_missing_dependency(
                operation=op,
                dependency=str((legacy or {}).get("dependency") or "unknown"),
            )
        )

    if not backend_available:
        return _annotate(
            unavailable_missing_backend(
                operation=op,
                backend=str((legacy or {}).get("backend") or "ipfs"),
            )
        )

    legacy_payload = dict(legacy or {})
    legacy_payload.setdefault("defect_family", family_name)
    if simulated or family_name in {
        "upload_mock_cid_success",
        "download_mock_content_success",
        "cluster_upload_download_mock_success",
        "dataset_tool_mock_save_success",
        "simulated_upload_cid",
        "semantic_result_simulated_success",
    }:
        legacy_payload.setdefault("simulated", True)
        legacy_payload.setdefault("status", "success")
        legacy_payload.setdefault("durable_effect", False)

    if family_name in {
        "download_fallback_stub_success",
        "download_placeholder_success",
        "upload_placeholder_success",
    }:
        legacy_payload.setdefault("status", "success")
        legacy_payload.setdefault("durable_effect", False)
        if attempt_evidenced:
            legacy_payload["attempt_evidenced"] = True

    if observation_present:
        legacy_payload["observation_present"] = True
        legacy_payload["durable_effect"] = True
        legacy_payload["independent_effect_observation"] = True

    return _annotate(
        project_compatibility(
            legacy_payload,
            operation=op,
            defect_family=family_name,
        )
    )


def _default_operation_for_family(family: str) -> OperationKind:
    if "semantic" in family:
        return "semantic"
    if "cluster" in family:
        return "cluster"
    if "upload" in family or "save" in family or "pin" in family or "cid" in family:
        if "pin" in family:
            return "pin"
        if "save" in family:
            return "save"
        if family == "simulated_upload_cid":
            return "backend_add"
        return "upload"
    if "download" in family or "get" in family or "content" in family:
        if "get" in family or "content" in family:
            return "get" if "content" in family else "download"
        return "download"
    return "download"


def resolve_download_outcome(
    *,
    backend_available: bool,
    dependency_available: bool = True,
    attempt_evidenced: bool = False,
    observation_present: bool = False,
    observation_id: str | None = None,
    admission_token: str | None = None,
    family: str = "download_fallback_stub_success",
) -> DatasetOutcome:
    """Typed download outcome replacing fallback/placeholder/mock success."""
    if not dependency_available:
        return replace_false_success_fallback(
            family=family,
            operation="download",
            backend_available=backend_available,
            dependency_available=False,
        )
    if not backend_available:
        return replace_false_success_fallback(
            family=family,
            operation="download",
            backend_available=False,
        )
    if observation_present:
        attempt = begin_attempt(operation="download")
        return bind_effect_observation(
            attempt,
            observation_present=True,
            observation_id=observation_id or "download-observation",
            admission_token=admission_token or "admission:download",
        )
    if attempt_evidenced:
        return begin_attempt(operation="download")
    return replace_false_success_fallback(
        family=family,
        operation="download",
        backend_available=True,
        attempt_evidenced=False,
        observation_present=False,
    )


def resolve_upload_outcome(
    *,
    backend_available: bool,
    dependency_available: bool = True,
    attempt_evidenced: bool = False,
    observation_present: bool = False,
    observation_id: str | None = None,
    admission_token: str | None = None,
    family: str = "upload_placeholder_success",
    allow_simulated_cid: bool = False,
) -> DatasetOutcome:
    """Typed upload/pin outcome; simulated CIDs never become success."""
    if allow_simulated_cid:
        return replace_false_success_fallback(
            family="upload_mock_cid_success"
            if family == "upload_placeholder_success"
            else family,
            operation="upload",
            backend_available=backend_available,
            dependency_available=dependency_available,
            simulated=True,
        )
    if not dependency_available:
        return replace_false_success_fallback(
            family=family,
            operation="upload",
            dependency_available=False,
            backend_available=backend_available,
        )
    if not backend_available:
        return replace_false_success_fallback(
            family=family,
            operation="upload",
            backend_available=False,
        )
    if observation_present:
        attempt = begin_attempt(operation="upload")
        return bind_effect_observation(
            attempt,
            observation_present=True,
            observation_id=observation_id or "upload-observation",
            admission_token=admission_token or "admission:upload",
        )
    if attempt_evidenced:
        return begin_attempt(operation="upload")
    return replace_false_success_fallback(
        family=family,
        operation="upload",
        backend_available=True,
    )


def resolve_semantic_outcome(
    *,
    vector_store_available: bool,
    attempt_evidenced: bool = False,
    observation_present: bool = False,
    observation_id: str | None = None,
    admission_token: str | None = None,
    simulated_hits: bool = False,
) -> DatasetOutcome:
    """Typed semantic-search outcome; simulated hits stay Simulated."""
    family = "semantic_result_simulated_success"
    if not vector_store_available or simulated_hits:
        return replace_false_success_fallback(
            family=family,
            operation="semantic",
            backend_available=False if not vector_store_available else True,
            simulated=True,
            legacy={
                "backend": "vector_store",
                "note": (
                    "Simulated semantic search - full implementation requires "
                    "vector store integration"
                ),
                "status": "success",
                "durable_effect": False,
            },
        )
    if observation_present:
        attempt = begin_attempt(operation="semantic")
        return bind_effect_observation(
            attempt,
            observation_present=True,
            observation_id=observation_id or "semantic-observation",
            admission_token=admission_token or "admission:semantic",
        )
    if attempt_evidenced:
        return begin_attempt(operation="semantic")
    return unavailable_missing_backend(
        operation="semantic",
        backend="vector_store",
        details={"defect_family": family, "defect_id": INVENTORY_DEFECT_IDS[family]},
    )


def validate_delegated_receipt(
    receipt: Mapping[str, Any],
    *,
    operation: OperationKind | str = "download",
) -> DatasetOutcome:
    """Validate a delegated effect receipt without inventing success.

    Missing, unsigned, or observation-free receipts remain non-success.
    """
    if not receipt:
        return DatasetOutcome(
            outcome="Unavailable",
            code="delegated_receipt_missing",
            message="delegated receipt is missing",
            operation=operation,
            envelope=EvidenceEnvelope(),
            details={"receipt_present": False},
        )

    if receipt.get("revoked") is True or receipt.get("authority") == "revoked":
        return DatasetOutcome(
            outcome="Rejected",
            code="delegated_receipt_revoked",
            message="delegated receipt authority is revoked",
            operation=operation,
            envelope=EvidenceEnvelope(authority="revoked", effect="failed"),
            details={"receipt_id": receipt.get("receipt_id")},
        )

    has_observation = bool(receipt.get("independent_effect_observation"))
    has_signature = bool(
        receipt.get("signed_receipt") or receipt.get("signature_valid")
    )
    if not has_observation:
        return DatasetOutcome(
            outcome="Attempted" if receipt.get("attempt_evidenced") else "Unknown",
            code="delegated_receipt_unobserved",
            message="delegated receipt lacks independent effect observation",
            operation=operation,
            envelope=EvidenceEnvelope(
                effect="started" if receipt.get("attempt_evidenced") else "externally_unknown",
                integrity="structurally_valid" if has_signature else "unchecked",
            ),
            details={"receipt_id": receipt.get("receipt_id")},
        )

    if not has_signature:
        return DatasetOutcome(
            outcome="Unknown",
            code="delegated_receipt_unsigned",
            message="delegated receipt observation is unsigned",
            operation=operation,
            envelope=EvidenceEnvelope(effect="externally_unknown", integrity="unchecked"),
            evidence=frozenset({"independent_effect_observation"}),
            details={"receipt_id": receipt.get("receipt_id")},
        )

    attempt = begin_attempt(operation=operation)
    return bind_effect_observation(
        attempt,
        observation_present=True,
        observation_id=str(receipt.get("receipt_id") or "delegated-receipt"),
        admission_token=str(receipt.get("admission_token") or "admission:delegated"),
        origin="live_observed"
        if receipt.get("environment") == "live"
        else "hermetic_observed",
        integrity="signature_valid",
        details={"receipt_id": receipt.get("receipt_id"), "delegated": True},
    )


__all__ = [
    "TASK_ID",
    "GOAL_ID",
    "BUNDLE",
    "EVIDENCE_ID",
    "INTERFACE",
    "FCA_VOCABULARY_SCHEMA",
    "UNSAFE_PROMOTION",
    "CLOSED_OUTCOMES",
    "INVENTORIED_FALSE_SUCCESS_FAMILIES",
    "INVENTORY_DEFECT_IDS",
    "VERIFIER_ADMISSION_EVIDENCE",
    "VERIFIED_REQUIRED_EVIDENCE",
    "DatasetOutcomeError",
    "EvidenceEnvelope",
    "DatasetOutcome",
    "unavailable_missing_backend",
    "unavailable_missing_dependency",
    "begin_attempt",
    "bind_effect_observation",
    "admit_verified",
    "project_compatibility",
    "replace_false_success_fallback",
    "resolve_download_outcome",
    "resolve_upload_outcome",
    "resolve_semantic_outcome",
    "validate_delegated_receipt",
]
