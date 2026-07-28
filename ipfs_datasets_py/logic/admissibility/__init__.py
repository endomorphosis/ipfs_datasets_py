"""Intent admissibility gate package (profiles, reasons, composite join).

Public surface for LIG-G060:

* :mod:`profiles` — ``AdmissibilityProfile@1`` registry and fail-closed resolve
* :mod:`reasons` — closed ``AdmissibilityReason@1`` vocabulary
* :mod:`gate` — ``IntentAdmissibilityGate@1`` / ``AdmissibilityDecision@1``
"""

from __future__ import annotations

from .gate import (
    ADMISSIBILITY_DECISION_INTERFACE,
    ADMISSIBILITY_DECISION_SCHEMA_VERSION,
    ADMISSIBILITY_GATE_INTERFACE,
    ADMISSIBILITY_GATE_SCHEMA_VERSION,
    AdmissibilityDecision,
    AdmissibilityGateError,
    ConstraintPolarity,
    IntentAdmissibilityGate,
    classify_constraint_polarity,
    evaluate_admissibility,
    intent_has_unsupported_semantics,
    store_snapshot_digest,
)
from .profiles import (
    ADMISSIBILITY_PROFILE_INTERFACE_VERSION,
    DEFAULT_PROFILE_ID,
    PROFILE_ID_WIRE_VALUES,
    PROFILE_REGISTRY,
    PROFILE_SCHEMA_VERSION,
    AdmissibilityProfile,
    AdmissibilityProfileError,
    AdmissibilityProfileId,
    ProfileResolution,
    UnknownAdmissibilityProfileError,
    get_profile,
    is_known_profile,
    list_profiles,
    parse_profile_id,
    profile_id_set,
    resolve_profile,
    resolve_profile_fail_closed,
    stable_profile_id_values,
)
from .reasons import (
    ADMISSIBILITY_REASON_INTERFACE_VERSION,
    REASON_CODE_WIRE_VALUES,
    AdmissibilityReason,
    AdmissibilityReasonCode,
    AdmissibilityReasonError,
    AdmissibilityStatus,
    default_status_for_reason,
    invalid_profile_reason,
    parse_reason_code,
    parse_status,
    reason_code_set,
    stable_reason_code_values,
)

__all__ = [
    "ADMISSIBILITY_DECISION_INTERFACE",
    "ADMISSIBILITY_DECISION_SCHEMA_VERSION",
    "ADMISSIBILITY_GATE_INTERFACE",
    "ADMISSIBILITY_GATE_SCHEMA_VERSION",
    "ADMISSIBILITY_PROFILE_INTERFACE_VERSION",
    "ADMISSIBILITY_REASON_INTERFACE_VERSION",
    "DEFAULT_PROFILE_ID",
    "PROFILE_ID_WIRE_VALUES",
    "PROFILE_REGISTRY",
    "PROFILE_SCHEMA_VERSION",
    "REASON_CODE_WIRE_VALUES",
    "AdmissibilityDecision",
    "AdmissibilityGateError",
    "AdmissibilityProfile",
    "AdmissibilityProfileError",
    "AdmissibilityProfileId",
    "AdmissibilityReason",
    "AdmissibilityReasonCode",
    "AdmissibilityReasonError",
    "AdmissibilityStatus",
    "ConstraintPolarity",
    "IntentAdmissibilityGate",
    "ProfileResolution",
    "UnknownAdmissibilityProfileError",
    "classify_constraint_polarity",
    "default_status_for_reason",
    "evaluate_admissibility",
    "get_profile",
    "intent_has_unsupported_semantics",
    "invalid_profile_reason",
    "is_known_profile",
    "list_profiles",
    "parse_profile_id",
    "parse_reason_code",
    "parse_status",
    "profile_id_set",
    "reason_code_set",
    "resolve_profile",
    "resolve_profile_fail_closed",
    "stable_profile_id_values",
    "stable_reason_code_values",
    "store_snapshot_digest",
]
