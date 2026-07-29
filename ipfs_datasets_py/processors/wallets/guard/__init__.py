"""Custody-neutral wallet transaction guard contracts (CRYPTOIR-G500).

Public surface for exact transaction intent, serialized candidates, fail-closed
preflight evaluation, and request-bound one-use admissibility capabilities.

This package issues evidence-bound permission only.  Keys, interactive user
approval, signing, and broadcast remain the responsibility of an external
custody system.  Bare booleans and caller-supplied approval flags are never
authorization.
"""

from __future__ import annotations

from .errors import (
    GuardCapabilityError,
    GuardConsumptionRaceError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from .models import (
    ADMISSIBILITY_CAPABILITY_INTERFACE,
    ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION,
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    PREFLIGHT_CONSUMPTION_SCHEMA_VERSION,
    PREFLIGHT_RESULT_SCHEMA_VERSION,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TRANSACTION_CANDIDATE_INTERFACE,
    TRANSACTION_CANDIDATE_SCHEMA_VERSION,
    TRANSACTION_INTENT_INTERFACE,
    TRANSACTION_INTENT_SCHEMA_VERSION,
    TRANSACTION_PREFLIGHT_REQUEST_INTERFACE,
    TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
    UtxoRef,
)
from .preflight import (
    DEFAULT_ALLOWED_EFFECT,
    DEFAULT_PRODUCER_ID,
    REQUIREMENT_PASS,
    TRANSACTION_PREFLIGHT_INTERFACE,
    TRANSACTION_PREFLIGHT_SCHEMA_VERSION,
    TransactionPreflight,
    compose_requirement_outcomes,
    evaluate_transaction_preflight,
)

__all__ = [
    # errors
    "GuardCapabilityError",
    "GuardConsumptionRaceError",
    "GuardError",
    "GuardForbiddenSurfaceError",
    "GuardPolicyError",
    "GuardValidationError",
    # models
    "ADMISSIBILITY_CAPABILITY_INTERFACE",
    "ADMISSIBILITY_CAPABILITY_SCHEMA_VERSION",
    "AdmissibilityCapability",
    "AssetAmount",
    "ExpectedEffect",
    "FeeSpec",
    "PREFLIGHT_CONSUMPTION_SCHEMA_VERSION",
    "PREFLIGHT_RESULT_SCHEMA_VERSION",
    "PreflightConsumptionResult",
    "PreflightPhase",
    "PreflightResult",
    "TRANSACTION_CANDIDATE_INTERFACE",
    "TRANSACTION_CANDIDATE_SCHEMA_VERSION",
    "TRANSACTION_INTENT_INTERFACE",
    "TRANSACTION_INTENT_SCHEMA_VERSION",
    "TRANSACTION_PREFLIGHT_REQUEST_INTERFACE",
    "TRANSACTION_PREFLIGHT_REQUEST_SCHEMA_VERSION",
    "TransactionCandidate",
    "TransactionIntent",
    "TransactionPreflightRequest",
    "UtxoRef",
    # preflight
    "DEFAULT_ALLOWED_EFFECT",
    "DEFAULT_PRODUCER_ID",
    "REQUIREMENT_PASS",
    "TRANSACTION_PREFLIGHT_INTERFACE",
    "TRANSACTION_PREFLIGHT_SCHEMA_VERSION",
    "TransactionPreflight",
    "compose_requirement_outcomes",
    "evaluate_transaction_preflight",
]
