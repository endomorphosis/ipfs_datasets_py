"""Stable Python software-verification API facade.

``LogicVerificationAPI@1`` is the additive public surface for family/provider
discovery, compilation, checking, monitoring, portfolio planning, counterexample
explanation, receipt validation, advisor proposals, and receipt attestation.

Design invariants
-----------------
* Importing this module never probes the environment, installs packages,
  launches processes, mutates the filesystem, or opens network sockets.
* Discovery (``list_*``, ``provider_capabilities``) is purely declarative.
* Explicit ``probe_provider`` / ``install_provider`` operations are opt-in.
* Responses always expose typed status, authority, assumptions, bounds,
  translations, witnesses, and cache provenance.
* Absent or unavailable features are reported explicitly; they never become
  success by silence.
* Legacy ``logic.api`` imports remain unaffected; this facade is additive.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Optional

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest

LOGIC_VERIFICATION_API_INTERFACE: Final = "LogicVerificationAPI@1"
LOGIC_VERIFICATION_API_VERSION: Final = "1.0.0"
LOGIC_VERIFICATION_RESPONSE_SCHEMA: Final = "logic-verification-response/v1"
LOGIC_VERIFICATION_FEATURE_SCHEMA: Final = "logic-verification-feature/v1"
LOGIC_VERIFICATION_PROVIDER_SCHEMA: Final = "logic-verification-provider/v1"
LOGIC_VERIFICATION_CACHE_SCHEMA: Final = "logic-verification-cache-provenance/v1"
LOGIC_VERIFICATION_REQUEST_SCHEMA: Final = "logic-verification-request/v1"
# FVT-G012 / ExecutableProviderMatrix@1 surface identity (lazy full matrix).
EXECUTABLE_PROVIDER_MATRIX_INTERFACE: Final = "ExecutableProviderMatrix@1"
FORMAL_VERIFICATION_MCP_PARITY_INTERFACE: Final = "FormalVerificationMCPParity@1"

# FVT-G050 / GoalTacticianAPI@1 + GoalTacticianCLIMCP@1 (goal-directed public surface).
GOAL_TACTICIAN_API_INTERFACE: Final = "GoalTacticianAPI@1"
GOAL_TACTICIAN_API_VERSION: Final = "1.0.0"
GOAL_TACTICIAN_CLI_MCP_INTERFACE: Final = "GoalTacticianCLIMCP@1"
GOAL_TACTICIAN_REQUEST_SCHEMA: Final = "goal-tactician-request/v1"
GOAL_TACTICIAN_RESPONSE_SCHEMA: Final = "logic-verification-response/v1"

# Closed receipt/attestation dispatch surfaces (FVT-G006 / VerifiedReceiptDispatch@2).
VERIFIED_RECEIPT_DISPATCH_INTERFACE: Final = "VerifiedReceiptDispatch@2"
ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE: Final = "AttestationAuthorityBoundary@2"
TRUSTED_PROOF_RECEIPT_SCHEMA: Final = "trusted-proof-receipt/v1"
LOGIC_TRANSLATION_RECEIPT_SCHEMA: Final = "logic-translation-receipt/v1"
CLOSED_RECEIPT_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        TRUSTED_PROOF_RECEIPT_SCHEMA,
        LOGIC_TRANSLATION_RECEIPT_SCHEMA,
    }
)

# Operations advertised by the stable surface (LFV-G070 / plan § Stable logic API).
# Kept closed for legacy MCP parity; goal-tactician ops live in GOAL_TACTICIAN_OPERATIONS.
STABLE_OPERATIONS: Final[tuple[str, ...]] = (
    "list_logic_families",
    "list_providers",
    "provider_capabilities",
    "compile_verification_artifact",
    "check",
    "monitor",
    "run_portfolio",
    "explain_counterexample",
    "verify_receipt",
    "attest_receipt",
    "advise",
    "probe_provider",
    "install_provider",
)

# Additive GoalTacticianAPI@1 operations (FVT-G050).  Not merged into
# STABLE_OPERATIONS so LogicVerificationMCP@1 legacy mappings stay intact.
GOAL_TACTICIAN_OPERATIONS: Final[tuple[str, ...]] = (
    "formalize_goal",
    "compare_interpretations",
    "discover_missing_proofs",
    "plan_proof",
    "validate_proof_candidate",
    "execute_proof_plan",
    "proof_status",
    "minimize_counterexample",
    "explain_counterexample_causal",
    "replay_counterexample",
    "list_goal_tactician_operations",
)

# Supervisor-only controls that datasets public surfaces must never expose.
_GOAL_TACTICIAN_FORBIDDEN_CONTROLS: Final[frozenset[str]] = frozenset(
    {
        "admit_goal",
        "close_plan",
        "mutate_supervisor",
        "force_complete",
        "lease_steal",
        "rewrite_event_log",
        "bypass_resource_policy",
        "promote_proof_authority",
        "supervisor_mutate",
        "supervisor_only",
    }
)

# Channel-neutral CLI / MCP descriptors for GoalTacticianCLIMCP@1.
GOAL_TACTICIAN_TOOL_TO_OPERATION: Final[dict[str, str]] = {
    "goal_tactician_formalize_goal": "formalize_goal",
    "goal_tactician_compare_interpretations": "compare_interpretations",
    "goal_tactician_discover_missing_proofs": "discover_missing_proofs",
    "goal_tactician_plan_proof": "plan_proof",
    "goal_tactician_validate_proof_candidate": "validate_proof_candidate",
    "goal_tactician_execute_proof_plan": "execute_proof_plan",
    "goal_tactician_proof_status": "proof_status",
    "goal_tactician_minimize_counterexample": "minimize_counterexample",
    "goal_tactician_explain_counterexample_causal": "explain_counterexample_causal",
    "goal_tactician_replay_counterexample": "replay_counterexample",
    "goal_tactician_list_operations": "list_goal_tactician_operations",
}

GOAL_TACTICIAN_CLI_TO_OPERATION: Final[dict[str, str]] = {
    "goal-formalize": "formalize_goal",
    "goal-compare-interpretations": "compare_interpretations",
    "goal-discover-missing-proofs": "discover_missing_proofs",
    "goal-plan-proof": "plan_proof",
    "goal-validate-candidate": "validate_proof_candidate",
    "goal-execute-plan": "execute_proof_plan",
    "goal-proof-status": "proof_status",
    "goal-minimize-counterexample": "minimize_counterexample",
    "goal-explain-counterexample": "explain_counterexample_causal",
    "goal-replay-counterexample": "replay_counterexample",
    "goal-list-operations": "list_goal_tactician_operations",
}

GOAL_TACTICIAN_TOOL_NAMES: Final[tuple[str, ...]] = tuple(GOAL_TACTICIAN_TOOL_TO_OPERATION.keys())
GOAL_TACTICIAN_CLI_COMMANDS: Final[tuple[str, ...]] = tuple(GOAL_TACTICIAN_CLI_TO_OPERATION.keys())


class VerificationStatus(StrEnum):
    """Terminal status for a stable verification API response."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    ERROR = "error"
    DECLARATIVE = "declarative"


class FeatureAvailability(StrEnum):
    """Whether a feature is present, optional, or explicitly absent."""

    DECLARED = "declared"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ABSENT = "absent"
    OPT_IN = "opt_in"


class VerificationAuthority(StrEnum):
    """Authority ceiling carried by a response (never silently upgraded)."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    SATISFIABILITY = "satisfiability"
    MODEL_CHECK = "model_check"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    CANDIDATE = "candidate"
    RECONSTRUCTION = "reconstruction"
    ATTESTATION = "attestation"
    THEOREM = "theorem"
    DECLARATIVE = "declarative"


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise VerificationAPIError(f"{label} must be a non-empty trimmed string without NUL")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise VerificationAPIError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _string_tuple(values: object, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise VerificationAPIError(f"{label} must be a sequence of strings")
    result: list[str] = []
    for item in values:
        result.append(_text(item, f"{label} item"))
    return tuple(result)


class VerificationAPIError(ValueError):
    """Raised when a verification API request is malformed."""


@dataclass(frozen=True, slots=True)
class CacheProvenance:
    """Where a result came from and how fresh it is."""

    source: str = "live"
    hit: bool = False
    cache_key: str = ""
    scope: str = "none"
    freshness: str = "not_cached"
    schema_version: str = LOGIC_VERIFICATION_CACHE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "freshness": self.freshness,
            "hit": self.hit,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class FeatureDescriptor:
    """Declarative description of one stable API operation or capability."""

    feature_id: str
    availability: FeatureAvailability
    description: str = ""
    authority_ceiling: VerificationAuthority = VerificationAuthority.NONE
    requires_opt_in: bool = False
    notes: str = ""
    schema_version: str = LOGIC_VERIFICATION_FEATURE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "description": self.description,
            "feature_id": self.feature_id,
            "notes": self.notes,
            "requires_opt_in": self.requires_opt_in,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Inert provider/backend declaration used by discovery."""

    provider_id: str
    provider_version: str = "declared"
    logic_families: tuple[str, ...] = ()
    query_kinds: tuple[str, ...] = ()
    deterministic: bool = True
    availability: FeatureAvailability = FeatureAvailability.DECLARED
    source: str = "backend_registry"
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LOGIC_VERIFICATION_PROVIDER_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "deterministic": self.deterministic,
            "logic_families": list(self.logic_families),
            "metadata": self.metadata.to_dict()
            if hasattr(self.metadata, "to_dict")
            else dict(self.metadata),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "query_kinds": list(self.query_kinds),
            "schema_version": self.schema_version,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class VerificationResponse:
    """Uniform envelope for every stable verification operation."""

    operation: str
    status: VerificationStatus
    authority: VerificationAuthority = VerificationAuthority.NONE
    result: Mapping[str, Any] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    bounds: Mapping[str, Any] = field(default_factory=dict)
    translations: tuple[Mapping[str, Any], ...] = ()
    witnesses: tuple[Mapping[str, Any], ...] = ()
    unsupported_features: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    cache: CacheProvenance = field(default_factory=CacheProvenance)
    request_id: str = ""
    property_id: str = ""
    provider_id: str = ""
    interface: str = LOGIC_VERIFICATION_API_INTERFACE
    api_version: str = LOGIC_VERIFICATION_API_VERSION
    schema_version: str = LOGIC_VERIFICATION_RESPONSE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _text(self.operation, "operation"))
        if not isinstance(self.status, VerificationStatus):
            object.__setattr__(self, "status", VerificationStatus(self.status))
        if not isinstance(self.authority, VerificationAuthority):
            object.__setattr__(self, "authority", VerificationAuthority(self.authority))
        object.__setattr__(self, "result", MappingProxyType(dict(self.result)))
        object.__setattr__(self, "assumptions", _string_tuple(self.assumptions, "assumptions"))
        object.__setattr__(self, "bounds", MappingProxyType(_mapping(self.bounds, "bounds")))
        translations = tuple(
            MappingProxyType(dict(item)) if isinstance(item, Mapping) else item
            for item in self.translations
        )
        object.__setattr__(self, "translations", translations)
        witnesses = tuple(
            MappingProxyType(dict(item)) if isinstance(item, Mapping) else item
            for item in self.witnesses
        )
        object.__setattr__(self, "witnesses", witnesses)
        object.__setattr__(
            self,
            "unsupported_features",
            _string_tuple(self.unsupported_features, "unsupported_features"),
        )
        object.__setattr__(self, "diagnostics", _string_tuple(self.diagnostics, "diagnostics"))
        if not isinstance(self.cache, CacheProvenance):
            raise VerificationAPIError("cache must be a CacheProvenance")

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "assumptions": list(self.assumptions),
            "authority": self.authority.value,
            "bounds": dict(self.bounds),
            "cache": self.cache.to_dict(),
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "operation": self.operation,
            "property_id": self.property_id,
            "provider_id": self.provider_id,
            "request_id": self.request_id,
            "result": dict(self.result),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "translations": [dict(item) for item in self.translations],
            "unsupported_features": list(self.unsupported_features),
            "witnesses": [dict(item) for item in self.witnesses],
        }


def _empty_cache(*, source: str = "declarative") -> CacheProvenance:
    return CacheProvenance(
        source=source,
        hit=False,
        cache_key="",
        scope="none",
        freshness="not_cached",
    )


def _response(
    operation: str,
    status: VerificationStatus,
    *,
    authority: VerificationAuthority = VerificationAuthority.NONE,
    result: Mapping[str, Any] | None = None,
    assumptions: Sequence[str] = (),
    bounds: Mapping[str, Any] | None = None,
    translations: Sequence[Mapping[str, Any]] = (),
    witnesses: Sequence[Mapping[str, Any]] = (),
    unsupported_features: Sequence[str] = (),
    diagnostics: Sequence[str] = (),
    cache: CacheProvenance | None = None,
    request_id: str = "",
    property_id: str = "",
    provider_id: str = "",
) -> VerificationResponse:
    return VerificationResponse(
        operation=operation,
        status=status,
        authority=authority,
        result=dict(result or {}),
        assumptions=tuple(assumptions),
        bounds=dict(bounds or {}),
        translations=tuple(translations),
        witnesses=tuple(witnesses),
        unsupported_features=tuple(unsupported_features),
        diagnostics=tuple(diagnostics),
        cache=cache or _empty_cache(),
        request_id=request_id,
        property_id=property_id,
        provider_id=provider_id,
    )


def _lazy_family_registry():
    from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY

    return DEFAULT_REGISTRY


def _lazy_backend_registry():
    from ipfs_datasets_py.logic.backends.registry import default_backend_registry

    return default_backend_registry()


def _lazy_declared_backends():
    from ipfs_datasets_py.logic.backends.registry import declared_backend_catalog

    return declared_backend_catalog()


def list_stable_features() -> tuple[FeatureDescriptor, ...]:
    """Return the closed set of stable operations and their availability."""

    declared = (
        "list_logic_families",
        "list_providers",
        "provider_capabilities",
        "compile_verification_artifact",
        "check",
        "monitor",
        "run_portfolio",
        "explain_counterexample",
        "verify_receipt",
        "advise",
    )
    opt_in = ("probe_provider", "install_provider", "attest_receipt")
    features: list[FeatureDescriptor] = []
    for feature_id in declared:
        authority = VerificationAuthority.DECLARATIVE
        if feature_id in {"check", "monitor", "run_portfolio"}:
            authority = VerificationAuthority.BOUNDED
        elif feature_id in {"verify_receipt", "compile_verification_artifact"}:
            authority = VerificationAuthority.BOUNDED
        elif feature_id == "advise":
            authority = VerificationAuthority.ADVISORY
        elif feature_id == "explain_counterexample":
            authority = VerificationAuthority.BOUNDED
        features.append(
            FeatureDescriptor(
                feature_id=feature_id,
                availability=FeatureAvailability.DECLARED,
                description=f"Stable operation {feature_id}",
                authority_ceiling=authority,
            )
        )
    for feature_id in opt_in:
        authority = (
            VerificationAuthority.ATTESTATION
            if feature_id == "attest_receipt"
            else VerificationAuthority.NONE
        )
        features.append(
            FeatureDescriptor(
                feature_id=feature_id,
                availability=FeatureAvailability.OPT_IN,
                description=f"Explicit opt-in operation {feature_id}",
                authority_ceiling=authority,
                requires_opt_in=True,
                notes="Never invoked by discovery; requires an explicit call.",
            )
        )
    # Additive GoalTacticianAPI@1 discovery (does not alter STABLE_OPERATIONS).
    for feature_id in GOAL_TACTICIAN_OPERATIONS:
        authority = (
            VerificationAuthority.DECLARATIVE
            if feature_id == "list_goal_tactician_operations"
            else VerificationAuthority.BOUNDED
        )
        if feature_id in {
            "formalize_goal",
            "compare_interpretations",
            "plan_proof",
            "discover_missing_proofs",
        }:
            authority = VerificationAuthority.ADVISORY
        features.append(
            FeatureDescriptor(
                feature_id=feature_id,
                availability=FeatureAvailability.DECLARED,
                description=f"Goal tactician operation {feature_id}",
                authority_ceiling=authority,
                notes=GOAL_TACTICIAN_API_INTERFACE,
            )
        )
    return tuple(features)


def _is_cancelled(cancellation: object | None) -> bool:
    """Interpret optional cancellation tokens without importing supervisor types."""

    if cancellation is None:
        return False
    if cancellation is True:
        return True
    if isinstance(cancellation, Mapping):
        if cancellation.get("cancelled") is True or cancellation.get("is_cancelled") is True:
            return True
        if str(cancellation.get("status") or "").strip().lower() in {
            "cancelled",
            "canceled",
            "abort",
            "aborted",
        }:
            return True
        return False
    checker = getattr(cancellation, "is_cancelled", None)
    if callable(checker):
        try:
            return bool(checker())
        except TypeError:
            try:
                return bool(checker)  # type: ignore[func-returns-value]
            except Exception:
                return False
    if getattr(cancellation, "cancelled", False) is True:
        return True
    if getattr(cancellation, "is_set", None) is not None:
        try:
            return bool(cancellation.is_set())  # type: ignore[union-attr]
        except Exception:
            return False
    return bool(cancellation)


def _redact_public_mapping(value: object, *, label: str = "payload") -> dict[str, Any]:
    """Drop private/secret channels from public response payloads."""

    forbidden_markers = (
        "secret",
        "password",
        "credential",
        "private_key",
        "raw_witness",
        "hidden_witness",
        "authorization_token",
        "api_key",
        "bearer",
    )

    def _walk(node: Any, *, path: str) -> Any:
        if isinstance(node, Mapping):
            cleaned: dict[str, Any] = {}
            for key, item in node.items():
                key_text = str(key)
                lowered = key_text.lower()
                if any(marker in lowered for marker in forbidden_markers):
                    continue
                if lowered in {"raw", "private", "secrets", "credentials", "stdin"}:
                    continue
                cleaned[key_text] = _walk(item, path=f"{path}.{key_text}")
            return cleaned
        if isinstance(node, (list, tuple)):
            return [_walk(item, path=f"{path}[]") for item in node]
        if isinstance(node, str) and len(node) > 16_384:
            return node[:16_384] + "…[truncated]"
        return node

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return {"value": _walk(value, path=label)}
    return _walk(value, path=label)


def _reject_forbidden_controls(payload: Mapping[str, Any] | None, operation: str) -> str | None:
    if not payload:
        return None
    keys = {str(key).strip().lower() for key in payload.keys()}
    meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
    keys |= {str(key).strip().lower() for key in meta.keys()}
    controls = payload.get("controls")
    if isinstance(controls, Mapping):
        keys |= {str(key).strip().lower() for key in controls.keys()}
    elif isinstance(controls, Sequence) and not isinstance(controls, (str, bytes)):
        keys |= {str(item).strip().lower() for item in controls}
    hit = sorted(keys & _GOAL_TACTICIAN_FORBIDDEN_CONTROLS)
    if hit:
        return (
            f"{operation} refuses supervisor-only control(s): {', '.join(hit)}; "
            "datasets GoalTacticianAPI never mutates supervisor state"
        )
    return None


def goal_tactician_tool_schemas() -> dict[str, dict[str, Any]]:
    """Closed MCP/CLI schemas for GoalTacticianCLIMCP@1 (channel-neutral)."""

    schemas: dict[str, dict[str, Any]] = {}
    for tool_name, operation in GOAL_TACTICIAN_TOOL_TO_OPERATION.items():
        schemas[tool_name] = {
            "name": tool_name,
            "interface": GOAL_TACTICIAN_CLI_MCP_INTERFACE,
            "python_operation": operation,
            "python_interface": GOAL_TACTICIAN_API_INTERFACE,
            "description": f"Goal tactician operation {operation}",
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "description": "Closed goal-tactician request payload",
                    },
                    "request_id": {"type": "string"},
                    "cancellation": {
                        "type": "object",
                        "description": "Optional cancellation token / flag",
                    },
                },
            },
            "returns": {
                "envelope": GOAL_TACTICIAN_RESPONSE_SCHEMA,
                "interface": LOGIC_VERIFICATION_API_INTERFACE,
            },
            "bounds": {
                "redaction": "public",
                "cancellation": True,
                "supervisor_mutation": False,
            },
        }
    return schemas


def list_goal_tactician_cli_mcp_surface() -> dict[str, Any]:
    """Declarative GoalTacticianCLIMCP@1 discovery document."""

    return {
        "interface": GOAL_TACTICIAN_CLI_MCP_INTERFACE,
        "python_interface": GOAL_TACTICIAN_API_INTERFACE,
        "python_version": GOAL_TACTICIAN_API_VERSION,
        "response_schema": GOAL_TACTICIAN_RESPONSE_SCHEMA,
        "request_schema": GOAL_TACTICIAN_REQUEST_SCHEMA,
        "operations": list(GOAL_TACTICIAN_OPERATIONS),
        "tools": list(GOAL_TACTICIAN_TOOL_NAMES),
        "tool_to_operation": dict(GOAL_TACTICIAN_TOOL_TO_OPERATION),
        "cli_commands": list(GOAL_TACTICIAN_CLI_COMMANDS),
        "cli_to_operation": dict(GOAL_TACTICIAN_CLI_TO_OPERATION),
        "schemas": goal_tactician_tool_schemas(),
        "forbidden_controls": sorted(_GOAL_TACTICIAN_FORBIDDEN_CONTROLS),
        "legacy_operations_preserved": list(STABLE_OPERATIONS),
        "transport_success_implies_proof_success": False,
    }


def _evidence_to_verification_authority(value: object) -> VerificationAuthority:
    """Map evidence ceilings onto the stable verification authority ladder.

    Translation receipts never become theorem authority.  Unknown ceilings fail
    closed to :attr:`VerificationAuthority.NONE`.
    """

    raw = str(getattr(value, "value", value) or "none").strip().lower()
    if raw in {"none", ""}:
        return VerificationAuthority.NONE
    if raw in {"advisory"}:
        return VerificationAuthority.ADVISORY
    if raw in {"bounded", "independently_checkable", "authoritative"}:
        return VerificationAuthority.BOUNDED
    try:
        return VerificationAuthority(raw)
    except ValueError:
        return VerificationAuthority.NONE


def _result_to_verification_authority(value: object) -> VerificationAuthority:
    """Map backend result authorities without silent upgrade."""

    raw = str(getattr(value, "value", value) or "none").strip().lower()
    if raw in {"", "none"}:
        return VerificationAuthority.NONE
    try:
        return VerificationAuthority(raw)
    except ValueError:
        return VerificationAuthority.NONE


def _normalize_string_set(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        return (str(values),)
    if not isinstance(values, Sequence):
        raise VerificationAPIError("sequence of strings required")
    return tuple(sorted(str(item) for item in values))


def _normalize_bounds(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized: dict[str, Any] = {}
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                bound_id = str(item.get("bound_id") or item.get("id") or index)
                normalized[bound_id] = dict(item)
            else:
                normalized[str(index)] = item
        return normalized
    if hasattr(value, "to_dict"):
        return _normalize_bounds(value.to_dict())
    raise VerificationAPIError("bounds must be a mapping or sequence of bound records")


def _receipt_payload(receipt: Any) -> dict[str, Any]:
    if receipt is None:
        raise VerificationAPIError("receipt is required")
    if hasattr(receipt, "to_dict") and callable(receipt.to_dict):
        payload = receipt.to_dict()
        if not isinstance(payload, Mapping):
            raise VerificationAPIError("receipt.to_dict() must return a mapping")
        return dict(payload)
    if isinstance(receipt, Mapping):
        return dict(receipt)
    raise VerificationAPIError("receipt must be a mapping or record with to_dict()")


def _schema_version_of(payload: Mapping[str, Any], receipt: Any) -> str:
    for candidate in (
        payload.get("schema_version"),
        getattr(receipt, "schema_version", None),
        getattr(getattr(receipt, "__class__", None), "SCHEMA_VERSION", None),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _dispatch_receipt_kind(schema_version: str) -> str:
    if schema_version == TRUSTED_PROOF_RECEIPT_SCHEMA:
        return "trusted_proof"
    if schema_version == LOGIC_TRANSLATION_RECEIPT_SCHEMA:
        return "translation"
    return ""


def _trusted_binding_issues(
    receipt: Any,
    expectation: Mapping[str, Any],
) -> list[str]:
    """Exact binding checks for trusted-proof-receipt/v1 against an expectation."""

    issues: list[str] = []
    tree_id = expectation.get("tree_id")
    if tree_id is not None and str(tree_id) != str(receipt.tree_id):
        issues.append(f"wrong-tree: expected {tree_id!r}, got {receipt.tree_id!r}")

    property_id = expectation.get("property_id")
    if property_id is not None and str(property_id) != str(receipt.property_id):
        issues.append(
            f"wrong-property: expected {property_id!r}, got {receipt.property_id!r}"
        )

    if "assumptions" in expectation:
        expected_assumptions = _normalize_string_set(expectation.get("assumptions"))
        actual_assumptions = tuple(sorted(str(item) for item in receipt.assumptions))
        if expected_assumptions != actual_assumptions:
            issues.append(
                "wrong-assumption: expected "
                f"{list(expected_assumptions)!r}, got {list(actual_assumptions)!r}"
            )

    if "bounds" in expectation:
        metadata = (
            receipt.metadata.to_dict()
            if hasattr(receipt.metadata, "to_dict")
            else dict(receipt.metadata)
        )
        actual_bounds = _normalize_bounds(metadata.get("bounds", {}))
        expected_bounds = _normalize_bounds(expectation.get("bounds"))
        if expected_bounds != actual_bounds:
            issues.append(
                f"wrong-bound: expected {expected_bounds!r}, got {actual_bounds!r}"
            )

    tool = expectation.get("tool_id", expectation.get("backend_id"))
    if tool is not None and str(tool) != str(receipt.backend_id):
        issues.append(f"wrong-tool: expected {tool!r}, got {receipt.backend_id!r}")

    if "authority" in expectation:
        expected_authority = str(
            getattr(expectation["authority"], "value", expectation["authority"])
        ).strip().lower()
        actual_authority = str(receipt.underlying_authority.value)
        if expected_authority != actual_authority:
            issues.append(
                "cross-authority: expected "
                f"{expected_authority!r}, got {actual_authority!r}"
            )

    if "source_result_digest" in expectation:
        expected_digest = str(expectation["source_result_digest"])
        if expected_digest != str(receipt.source_result_digest):
            issues.append(
                "stale: source_result_digest mismatch "
                f"(expected {expected_digest!r}, got {receipt.source_result_digest!r})"
            )

    claimed_content = expectation.get("content_id")
    if claimed_content is not None and str(claimed_content) != str(receipt.content_id):
        issues.append(
            "forged identity: content_id does not match trusted receipt payload"
        )

    if "receipt_id" in expectation and str(expectation["receipt_id"]) != str(
        receipt.receipt_id
    ):
        issues.append(
            f"stale: receipt_id mismatch (expected {expectation['receipt_id']!r}, "
            f"got {receipt.receipt_id!r})"
        )

    # Freshness window when the expectation or metadata carries temporal bounds.
    metadata = (
        receipt.metadata.to_dict()
        if hasattr(receipt.metadata, "to_dict")
        else dict(receipt.metadata)
    )
    now = expectation.get("now") or expectation.get("as_of")
    expires_at = expectation.get("expires_at") or metadata.get("expires_at")
    issued_at = expectation.get("issued_at") or metadata.get("issued_at")
    if now and expires_at:
        if str(now) > str(expires_at):
            issues.append(
                f"stale: receipt expired (as_of={now!r}, expires_at={expires_at!r})"
            )
    if now and issued_at and str(now) < str(issued_at):
        issues.append(
            f"stale: receipt not yet valid (as_of={now!r}, issued_at={issued_at!r})"
        )

    return issues


class LogicVerificationAPI:
    """Facade implementing :data:`LOGIC_VERIFICATION_API_INTERFACE`."""

    interface: Final = LOGIC_VERIFICATION_API_INTERFACE
    version: Final = LOGIC_VERIFICATION_API_VERSION

    def __init__(self, *, backend_registry: Any | None = None) -> None:
        self._backend_registry = backend_registry

    def _registry(self) -> Any:
        if self._backend_registry is not None:
            return self._backend_registry
        return _lazy_backend_registry()

    # ── Discovery (side-effect free) ──────────────────────────────────────

    def list_logic_families(self) -> VerificationResponse:
        """Return the declarative logic-family catalog."""

        registry = _lazy_family_registry()
        families = []
        for family_id in sorted(registry.families):
            descriptor = registry.family(family_id)
            payload = descriptor.to_dict() if hasattr(descriptor, "to_dict") else {"family_id": family_id}
            families.append(payload)
        return _response(
            "list_logic_families",
            VerificationStatus.DECLARATIVE,
            authority=VerificationAuthority.DECLARATIVE,
            result={
                "families": families,
                "count": len(families),
                "registry_version": getattr(registry, "version", ""),
                "schema_version": getattr(registry, "schema_version", ""),
            },
            cache=_empty_cache(source="family_registry"),
        )

    def list_providers(self) -> VerificationResponse:
        """Return declared providers/backends without availability probes."""

        catalog = _lazy_declared_backends()
        providers = [item if isinstance(item, dict) else item.to_dict() for item in catalog]
        # Taxonomy-level provider capabilities (may be empty).
        family_registry = _lazy_family_registry()
        taxonomy_caps = family_registry.provider_capabilities
        for provider_id in sorted(taxonomy_caps):
            descriptor = taxonomy_caps[provider_id]
            payload = descriptor.to_dict() if hasattr(descriptor, "to_dict") else {"provider_id": provider_id}
            providers.append(
                {
                    "provider_id": payload.get("provider_id", provider_id),
                    "provider_version": payload.get("provider_version", payload.get("version", "declared")),
                    "logic_families": [
                        item.get("family_id", item) if isinstance(item, Mapping) else str(item)
                        for item in payload.get("family_support", ())
                    ],
                    "query_kinds": [],
                    "deterministic": payload.get("deterministic"),
                    "availability": FeatureAvailability.DECLARED.value,
                    "source": "family_taxonomy",
                    "metadata": payload.get("metadata", {}),
                    "schema_version": LOGIC_VERIFICATION_PROVIDER_SCHEMA,
                }
            )
        providers.sort(key=lambda item: str(item.get("provider_id", "")))
        return _response(
            "list_providers",
            VerificationStatus.DECLARATIVE,
            authority=VerificationAuthority.DECLARATIVE,
            result={
                "providers": providers,
                "count": len(providers),
                "executable_provider_matrix": EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
            },
            cache=_empty_cache(source="provider_catalog"),
        )

    def provider_capabilities(
        self,
        provider_id: str | None = None,
    ) -> VerificationResponse:
        """Return capability declarations; never probes install state."""

        registry = self._registry()
        capabilities = dict(registry.capabilities)
        if provider_id:
            provider_id = _text(provider_id, "provider_id")
            if provider_id not in capabilities:
                return _response(
                    "provider_capabilities",
                    VerificationStatus.UNSUPPORTED,
                    authority=VerificationAuthority.DECLARATIVE,
                    result={"provider_id": provider_id, "capabilities": None},
                    unsupported_features=(f"provider:{provider_id}",),
                    diagnostics=(f"provider {provider_id!r} is not declared",),
                    provider_id=provider_id,
                )
            caps = capabilities[provider_id]
            payload = caps.to_dict() if hasattr(caps, "to_dict") else dict(caps)
            return _response(
                "provider_capabilities",
                VerificationStatus.DECLARATIVE,
                authority=VerificationAuthority.DECLARATIVE,
                result={"provider_id": provider_id, "capabilities": payload},
                provider_id=provider_id,
                cache=_empty_cache(source="backend_registry"),
            )
        declared = {
            backend_id: (
                caps.to_dict() if hasattr(caps, "to_dict") else dict(caps)
            )
            for backend_id, caps in sorted(capabilities.items())
        }
        return _response(
            "provider_capabilities",
            VerificationStatus.DECLARATIVE,
            authority=VerificationAuthority.DECLARATIVE,
            result={"capabilities": declared, "count": len(declared)},
            cache=_empty_cache(source="backend_registry"),
        )

    def list_features(self) -> VerificationResponse:
        """Return stable operation descriptors with explicit availability."""

        features = [item.to_dict() for item in list_stable_features()]
        return _response(
            "list_features",
            VerificationStatus.DECLARATIVE,
            authority=VerificationAuthority.DECLARATIVE,
            result={"features": features, "operations": list(STABLE_OPERATIONS)},
        )

    # ── Compilation ───────────────────────────────────────────────────────

    def compile_verification_artifact(
        self,
        artifact: Mapping[str, Any] | Any,
        *,
        target: str = "smtlib2",
        request_id: str = "",
    ) -> VerificationResponse:
        """Compile a verification obligation or IR fragment to a backend artifact.

        Heavy compiler modules are imported lazily so discovery stays free of
        optional tool dependencies.
        """

        target = _text(target, "target")
        request_id = _text(request_id, "request_id", optional=True)
        if target not in {"smtlib2", "smt", "smt-lib", "smt-lib2"}:
            return _response(
                "compile_verification_artifact",
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                result={"target": target},
                unsupported_features=(f"compile_target:{target}",),
                diagnostics=(f"compile target {target!r} is not supported by this facade",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.backends.smt.compiler import (
                SmtFeature,
                SmtObligation,
                SmtQueryMode,
                compile_obligation,
                term_true,
            )
        except Exception as error:  # pragma: no cover - import environment
            return _response(
                "compile_verification_artifact",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                result={"target": target},
                unsupported_features=("smt_compiler",),
                diagnostics=(f"SMT compiler unavailable: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        try:
            if isinstance(artifact, SmtObligation):
                obligation = artifact
            elif isinstance(artifact, Mapping):
                # Accept either a full SmtObligation mapping or a thin facade
                # request with obligation fields nested under "obligation".
                payload = dict(artifact)
                if "obligation" in payload and isinstance(payload["obligation"], Mapping):
                    payload = dict(payload["obligation"])
                if "obligation_id" not in payload:
                    payload.setdefault("obligation_id", request_id or "obl:facade")
                if "query_mode" not in payload:
                    payload.setdefault("query_mode", SmtQueryMode.SATISFIABILITY.value)
                if "features" not in payload or not payload.get("features"):
                    payload["features"] = (SmtFeature.EQUALITY,)
                if "goal" not in payload or payload.get("goal") in (None, ""):
                    payload["goal"] = term_true()
                obligation = (
                    SmtObligation.from_dict(payload)
                    if hasattr(SmtObligation, "from_dict")
                    else SmtObligation(**payload)  # type: ignore[arg-type]
                )
            else:
                raise VerificationAPIError(
                    "artifact must be an SmtObligation or mapping"
                )
            compilation = compile_obligation(obligation)
        except Exception as error:
            return _response(
                "compile_verification_artifact",
                VerificationStatus.INVALID
                if isinstance(error, (VerificationAPIError, TypeError, ValueError))
                else VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                result={"target": target},
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        compilation_dict = (
            compilation.to_dict() if hasattr(compilation, "to_dict") else {"compilation": str(compilation)}
        )
        translations = ()
        if hasattr(compilation, "receipt") and compilation.receipt is not None:
            receipt = compilation.receipt
            translations = (
                receipt.to_dict() if hasattr(receipt, "to_dict") else {"receipt": str(receipt)},
            )
        unsupported = ()
        if hasattr(obligation, "unsupported_constructs"):
            unsupported = tuple(
                item.construct if hasattr(item, "construct") else str(item)
                for item in obligation.unsupported_constructs
            )
        assumptions = ()
        if hasattr(obligation, "assumptions"):
            assumptions = tuple(
                item.name if hasattr(item, "name") else str(item)
                for item in obligation.assumptions
            )
        bounds: dict[str, Any] = {}
        if hasattr(obligation, "bounds") and obligation.bounds:
            bounds = {
                "items": [
                    item.to_dict() if hasattr(item, "to_dict") else str(item)
                    for item in obligation.bounds
                ]
            }
        return _response(
            "compile_verification_artifact",
            VerificationStatus.SUCCEEDED
            if not unsupported
            else VerificationStatus.PARTIAL,
            authority=VerificationAuthority.BOUNDED,
            result={
                "target": target,
                "compilation": compilation_dict,
                "obligation_id": getattr(obligation, "obligation_id", ""),
            },
            assumptions=assumptions,
            bounds=bounds,
            translations=translations,
            unsupported_features=unsupported,
            request_id=request_id,
            property_id=next(iter(getattr(obligation, "property_ids", ()) or ()), ""),
            cache=_empty_cache(source="compile"),
        )

    # ── Checking ──────────────────────────────────────────────────────────

    def check(
        self,
        request: Mapping[str, Any] | Any,
        *,
        backend_id: str | None = None,
        request_id: str = "",
    ) -> VerificationResponse:
        """Run a typed proof/satisfiability check through the backend registry."""

        request_id = _text(request_id, "request_id", optional=True)
        try:
            from ipfs_datasets_py.logic.ir_core.protocols import (
                BackendRequest,
                ExecutionBounds,
                QueryKind,
            )
            from ipfs_datasets_py.logic.ir_core.claims import FrozenMap as _FrozenMap
        except Exception as error:  # pragma: no cover
            return _response(
                "check",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"protocol import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        try:
            if isinstance(request, BackendRequest):
                backend_request = request
            elif isinstance(request, Mapping):
                payload = dict(request)
                query_kind = payload.get("query_kind", QueryKind.SATISFIABILITY)
                if not isinstance(query_kind, QueryKind):
                    query_kind = QueryKind(query_kind)
                bounds_payload = payload.get("bounds") or {}
                if isinstance(bounds_payload, ExecutionBounds):
                    bounds = bounds_payload
                elif isinstance(bounds_payload, Mapping):
                    bounds = ExecutionBounds(
                        timeout_ms=int(bounds_payload.get("timeout_ms", 30_000)),
                        max_steps=int(bounds_payload.get("max_steps", 100_000)),
                        max_memory_bytes=int(
                            bounds_payload.get("max_memory_bytes", 536_870_912)
                        ),
                        max_output_bytes=int(
                            bounds_payload.get("max_output_bytes", 1_048_576)
                        ),
                    )
                else:
                    bounds = ExecutionBounds()
                claim_digest = str(payload.get("claim_digest") or "").strip()
                obligation_digest = str(payload.get("obligation_digest") or "").strip()
                if len(claim_digest) != 64:
                    claim_digest = stable_digest(
                        {
                            "claim_id": payload.get("claim_id", "claim:facade"),
                            "statement": payload.get("statement", ""),
                        }
                    )
                if len(obligation_digest) != 64:
                    obligation_digest = stable_digest(
                        {
                            "obligation_id": payload.get("obligation_id", "obl:facade"),
                            "statement": payload.get("statement", ""),
                        }
                    )
                payload_map = payload.get("payload") or {
                    "statement": payload.get("statement", ""),
                    "encoding": payload.get("encoding", "smtlib2"),
                    "source": payload.get("source", payload.get("statement", "")),
                }
                backend_request = BackendRequest(
                    request_id=str(payload.get("request_id") or request_id or "req:facade"),
                    claim_id=str(payload.get("claim_id") or "claim:facade"),
                    declaration_id=str(payload.get("declaration_id") or "decl:facade"),
                    claim_digest=claim_digest,
                    obligation_id=str(payload.get("obligation_id") or "obl:facade"),
                    obligation_digest=obligation_digest,
                    assumption_ids=tuple(payload.get("assumption_ids") or ()),
                    logic_family=str(payload.get("logic_family") or "first_order"),
                    query_kind=query_kind,
                    bounds=bounds,
                    payload=_FrozenMap(payload_map)
                    if not isinstance(payload_map, _FrozenMap)
                    else payload_map,
                    requested_backend_id=str(
                        payload.get("requested_backend_id") or backend_id or ""
                    ),
                )
            else:
                raise VerificationAPIError("request must be a BackendRequest or mapping")
        except Exception as error:
            return _response(
                "check",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        registry = self._registry()
        selected = backend_id or backend_request.requested_backend_id
        supporting = registry.supporting(backend_request)
        registered_ids = set(registry)
        if selected and selected not in registered_ids:
            return _response(
                "check",
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                result={"requested_backend_id": selected, "supporting": list(supporting)},
                unsupported_features=(f"provider:{selected}",),
                diagnostics=(f"backend {selected!r} is not registered",),
                request_id=backend_request.request_id,
                provider_id=selected or "",
            )
        if not supporting and not selected:
            return _response(
                "check",
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                result={
                    "logic_family": backend_request.logic_family,
                    "query_kind": backend_request.query_kind.value,
                    "supporting": [],
                },
                unsupported_features=(
                    f"query:{backend_request.logic_family}/{backend_request.query_kind.value}",
                ),
                diagnostics=("no registered backend supports this request",),
                request_id=backend_request.request_id,
                bounds=backend_request.bounds.to_dict()
                if hasattr(backend_request.bounds, "to_dict")
                else {},
            )

        try:
            attempt, result = registry.run(
                backend_request,
                backend_id=selected or None,
            )
        except Exception as error:
            return _response(
                "check",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=backend_request.request_id,
                provider_id=selected or "",
                bounds=backend_request.bounds.to_dict()
                if hasattr(backend_request.bounds, "to_dict")
                else {},
            )

        result_status = getattr(result.status, "value", str(result.status))
        authority_value = getattr(
            getattr(result, "authority", None),
            "kind",
            None,
        )
        if authority_value is not None:
            authority_name = getattr(authority_value, "value", str(authority_value))
        else:
            authority_name = VerificationAuthority.BOUNDED.value
        try:
            authority = VerificationAuthority(authority_name)
        except ValueError:
            authority = VerificationAuthority.BOUNDED

        status = VerificationStatus.SUCCEEDED
        if result_status in {"unknown", "error"}:
            attempt_status = getattr(attempt.status, "value", str(attempt.status))
            if attempt_status == "unavailable":
                status = VerificationStatus.UNAVAILABLE
            elif attempt_status == "timed_out":
                status = VerificationStatus.ERROR
            else:
                status = VerificationStatus.ERROR

        witnesses: list[dict[str, Any]] = []
        payload = getattr(result, "payload", None)
        if payload is not None:
            payload_dict = payload.to_dict() if hasattr(payload, "to_dict") else dict(payload)
            if payload_dict:
                witnesses.append({"kind": "result_payload", "payload": payload_dict})
        if getattr(attempt, "output_digest", ""):
            witnesses.append(
                {
                    "kind": "output_digest",
                    "digest": attempt.output_digest,
                }
            )

        return _response(
            "check",
            status,
            authority=authority,
            result={
                "attempt": attempt.to_dict() if hasattr(attempt, "to_dict") else {"digest": getattr(attempt, "digest", "")},
                "result": result.to_dict() if hasattr(result, "to_dict") else {"status": result_status},
                "result_status": result_status,
                "supporting": list(supporting),
            },
            assumptions=tuple(backend_request.assumption_ids),
            bounds=backend_request.bounds.to_dict()
            if hasattr(backend_request.bounds, "to_dict")
            else {},
            witnesses=witnesses,
            diagnostics=tuple(getattr(attempt, "diagnostics", ()) or ()),
            request_id=backend_request.request_id,
            property_id=backend_request.obligation_id,
            provider_id=getattr(attempt, "backend_id", selected or ""),
            cache=CacheProvenance(
                source="backend_run",
                hit=False,
                cache_key=getattr(result, "request_digest", ""),
                scope="request",
                freshness="live",
            ),
        )

    # ── Monitoring ────────────────────────────────────────────────────────

    def monitor(
        self,
        formula: Any,
        observations: Sequence[Any] | Mapping[str, Any],
        *,
        request_id: str = "",
    ) -> VerificationResponse:
        """Evaluate a runtime MTL formula over observations (lazy import)."""

        request_id = _text(request_id, "request_id", optional=True)
        try:
            from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
                RuntimeMTLMonitor,
                evaluate_portable,
            )
        except Exception as error:
            return _response(
                "monitor",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("runtime_mtl",),
                diagnostics=(f"runtime MTL unavailable: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        try:
            if callable(evaluate_portable) and not isinstance(formula, type):
                # Prefer the portable evaluation helper when inputs match.
                evaluation = evaluate_portable(formula, observations)  # type: ignore[misc]
            else:
                monitor = RuntimeMTLMonitor(formula)
                evaluation = monitor.evaluate(observations)
        except Exception as error:
            # Fall back to constructing a monitor when portable eval rejects shapes.
            try:
                monitor = RuntimeMTLMonitor(formula)
                evaluation = monitor.evaluate(observations)
            except Exception as nested:
                return _response(
                    "monitor",
                    VerificationStatus.INVALID
                    if isinstance(error, (TypeError, ValueError))
                    else VerificationStatus.ERROR,
                    authority=VerificationAuthority.NONE,
                    diagnostics=(
                        f"{type(error).__name__}: {error}",
                        f"{type(nested).__name__}: {nested}",
                    ),
                    request_id=request_id,
                )

        evaluation_dict = (
            evaluation.to_dict()
            if hasattr(evaluation, "to_dict")
            else {"evaluation": str(evaluation)}
        )
        verdict = getattr(evaluation, "verdict", None) or getattr(evaluation, "status", None)
        witnesses = ()
        if hasattr(evaluation, "witness") and evaluation.witness is not None:
            witness = evaluation.witness
            witnesses = (
                witness.to_dict() if hasattr(witness, "to_dict") else {"witness": str(witness)},
            )
        return _response(
            "monitor",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.MONITOR,
            result={
                "evaluation": evaluation_dict,
                "verdict": getattr(verdict, "value", str(verdict) if verdict is not None else ""),
            },
            witnesses=witnesses,
            request_id=request_id,
            cache=_empty_cache(source="runtime_mtl"),
        )

    # ── Portfolio ─────────────────────────────────────────────────────────

    def run_portfolio(
        self,
        obligation: Mapping[str, Any] | Any,
        *,
        capabilities: Sequence[Any] | Mapping[str, Any] | None = None,
        resource_policy: Any | None = None,
        request_id: str = "",
        execute: bool = True,
        outcomes: Sequence[Any] | Mapping[str, Any] | None = None,
        probe_availability: bool = True,
    ) -> VerificationResponse:
        """Plan and (by default) execute a property-specific prover portfolio.

        When ``execute`` is true (default), planned runnable attempts are
        dispatched through the backend registry.  Unavailable lanes report
        unavailable outcomes rather than silent success.  Conflicting
        conclusive authorities quarantine via :func:`select_portfolio`.

        Pure planning is retained by setting ``execute=False``.  Callers may
        also supply precomputed ``outcomes`` for selection-only evaluation
        (used by tests and offline reconciliation).
        """

        request_id = _text(request_id, "request_id", optional=True)
        try:
            from ipfs_datasets_py.logic.backends.portfolio import (
                AttemptFamily,
                CapabilityStatus,
                PortfolioAttemptOutcome,
                PortfolioCapability,
                PortfolioObligation,
                PortfolioResourcePolicy,
                PortfolioVerdict,
                plan_portfolio,
                select_portfolio,
            )
            from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
            from ipfs_datasets_py.logic.software_verification.properties import PropertyKind
            from ipfs_datasets_py.logic.families.models import EvidenceAuthority
            from ipfs_datasets_py.logic.backends.registry import (
                PROVIDER_MATRIX_FAMILY_AUTHORIZATION,
                PROVIDER_MATRIX_FAMILY_ATP,
                PROVIDER_MATRIX_FAMILY_HAMMER,
                PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
                PROVIDER_MATRIX_FAMILY_KERNEL,
                PROVIDER_MATRIX_FAMILY_PROTOCOL,
                PROVIDER_MATRIX_FAMILY_RUNTIME,
                PROVIDER_MATRIX_FAMILY_SMT,
                PROVIDER_MATRIX_FAMILY_STATE_MODEL,
            )
        except Exception as error:
            return _response(
                "run_portfolio",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("verification_portfolio",),
                diagnostics=(f"portfolio module unavailable: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        family_map = {
            PROVIDER_MATRIX_FAMILY_SMT: AttemptFamily.SOLVER,
            PROVIDER_MATRIX_FAMILY_STATE_MODEL: AttemptFamily.MODEL_CHECKER,
            PROVIDER_MATRIX_FAMILY_RUNTIME: AttemptFamily.MONITOR,
            PROVIDER_MATRIX_FAMILY_AUTHORIZATION: AttemptFamily.POLICY,
            PROVIDER_MATRIX_FAMILY_PROTOCOL: AttemptFamily.PROTOCOL,
            PROVIDER_MATRIX_FAMILY_HYPERPROPERTY: AttemptFamily.HYPERPROPERTY,
            PROVIDER_MATRIX_FAMILY_ATP: AttemptFamily.ATP,
            PROVIDER_MATRIX_FAMILY_HAMMER: AttemptFamily.ORCHESTRATOR,
            PROVIDER_MATRIX_FAMILY_KERNEL: AttemptFamily.KERNEL,
        }

        try:
            if isinstance(obligation, PortfolioObligation):
                portfolio_obligation = obligation
            elif isinstance(obligation, Mapping):
                payload = dict(obligation)
                kind = payload.get("property_kind", PropertyKind.SATISFIABILITY)
                if not isinstance(kind, PropertyKind):
                    kind = PropertyKind(kind)
                assurance = payload.get("required_assurance", EvidenceAuthority.BOUNDED)
                if not isinstance(assurance, EvidenceAuthority):
                    assurance = EvidenceAuthority(assurance)
                portfolio_obligation = PortfolioObligation(
                    obligation_id=str(payload.get("obligation_id") or request_id or "obl:portfolio"),
                    property_kind=kind,
                    statement=str(payload.get("statement") or ""),
                    required_assurance=assurance,
                    assumption_ids=tuple(payload.get("assumption_ids") or ()),
                )
            else:
                raise VerificationAPIError("obligation must be PortfolioObligation or mapping")

            registry = self._registry()
            caps: list[Any] = []
            if capabilities is None:
                # Derive portfolio capabilities from the lazy matrix registry.
                for backend_id in registry:
                    backend = registry[backend_id]
                    backend_caps = backend.capabilities
                    matrix_entry = getattr(backend, "matrix_entry", None)
                    if matrix_entry is not None and getattr(matrix_entry, "family", ""):
                        family = family_map.get(
                            matrix_entry.family, AttemptFamily.SOLVER
                        )
                    else:
                        families = {
                            str(item).lower()
                            for item in (getattr(backend_caps, "logic_families", ()) or ())
                        }
                        family = AttemptFamily.SOLVER
                        if "hyperproperty" in families or "hyperltl" in families:
                            family = AttemptFamily.HYPERPROPERTY
                        elif "protocol" in families or "cryptographic_protocol" in families:
                            family = AttemptFamily.PROTOCOL
                        elif "authorization" in families or "policy" in families:
                            family = AttemptFamily.POLICY
                        elif "tla_plus" in families or "state_transition" in families:
                            family = AttemptFamily.MODEL_CHECKER
                        elif "runtime" in families:
                            family = AttemptFamily.MONITOR
                        elif backend_id in {"lean", "rocq", "isabelle"}:
                            family = AttemptFamily.KERNEL
                        elif backend_id in {"vampire", "eprover", "e"}:
                            family = AttemptFamily.ATP
                        elif backend_id == "hammer":
                            family = AttemptFamily.ORCHESTRATOR

                    status = CapabilityStatus.DECLARED
                    if execute and probe_availability:
                        try:
                            available = registry.is_available(backend_id)
                        except Exception:
                            available = False
                        status = (
                            CapabilityStatus.AVAILABLE
                            if available
                            else CapabilityStatus.UNAVAILABLE
                        )
                    caps.append(
                        PortfolioCapability(
                            backend_id=backend_id,
                            family=family,
                            status=status,
                            reconstruction_capable=(family is AttemptFamily.KERNEL),
                        )
                    )
            elif isinstance(capabilities, Mapping):
                raw_caps = list(capabilities.values())
                caps = []
                for item in raw_caps:
                    if isinstance(item, PortfolioCapability):
                        caps.append(item)
                    elif isinstance(item, Mapping):
                        caps.append(PortfolioCapability.from_dict(item))
                    else:
                        caps.append(item)
            else:
                caps = []
                for item in capabilities:
                    if isinstance(item, PortfolioCapability):
                        caps.append(item)
                    elif isinstance(item, Mapping):
                        caps.append(PortfolioCapability.from_dict(item))
                    else:
                        caps.append(item)

            policy = resource_policy
            if policy is None:
                policy = PortfolioResourcePolicy()
            plan = plan_portfolio(
                portfolio_obligation,
                capabilities=caps,
                resource_policy=policy,
            )
        except Exception as error:
            return _response(
                "run_portfolio",
                VerificationStatus.INVALID
                if isinstance(error, (VerificationAPIError, TypeError, ValueError))
                else VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else {"plan": str(plan)}
        gaps = []
        if hasattr(plan, "capability_gaps"):
            gaps = [
                gap.to_dict() if hasattr(gap, "to_dict") else str(gap)
                for gap in plan.capability_gaps
            ]
        unsupported = tuple(
            gap.get("backend_id", gap.get("reason", "gap"))
            if isinstance(gap, Mapping)
            else str(gap)
            for gap in gaps
        )

        executed_outcomes: list[Any] = []
        selection_dict: dict[str, Any] | None = None
        selection_authority = VerificationAuthority.BOUNDED
        status = VerificationStatus.SUCCEEDED if not gaps else VerificationStatus.PARTIAL
        cache_source = "portfolio_plan"

        if execute or outcomes is not None:
            cache_source = "portfolio_execution"
            try:
                if outcomes is not None:
                    recorded = outcomes
                else:
                    recorded = self._execute_portfolio_attempts(
                        plan,
                        portfolio_obligation,
                        registry=registry,
                    )
                    executed_outcomes = list(recorded) if isinstance(recorded, Sequence) else []

                selection = select_portfolio(plan, recorded)
                selection_dict = (
                    selection.to_dict() if hasattr(selection, "to_dict") else {"selection": str(selection)}
                )
                verdict = getattr(selection, "verdict", None)
                if verdict is PortfolioVerdict.QUARANTINED:
                    status = VerificationStatus.PARTIAL
                    selection_authority = VerificationAuthority.NONE
                elif verdict is PortfolioVerdict.PROVED:
                    status = VerificationStatus.SUCCEEDED
                    selection_authority = VerificationAuthority.BOUNDED
                    # Preserve typed authority ceiling from required authority when possible.
                    required = getattr(plan, "required_authority", None)
                    if required is not None:
                        mapped = _result_to_verification_authority(
                            getattr(required, "value", required)
                        )
                        if mapped is not VerificationAuthority.NONE:
                            selection_authority = mapped
                elif verdict is PortfolioVerdict.DISPROVED:
                    status = VerificationStatus.SUCCEEDED
                    selection_authority = VerificationAuthority.BOUNDED
                elif verdict is PortfolioVerdict.UNSUPPORTED:
                    status = VerificationStatus.UNSUPPORTED
                    selection_authority = VerificationAuthority.NONE
                elif verdict is PortfolioVerdict.UNAVAILABLE:
                    status = VerificationStatus.UNAVAILABLE
                    selection_authority = VerificationAuthority.NONE
                else:
                    status = VerificationStatus.PARTIAL
                    achieved = getattr(selection, "achieved_assurance", None)
                    if achieved is not None:
                        selection_authority = _evidence_to_verification_authority(achieved)
                    else:
                        selection_authority = VerificationAuthority.BOUNDED
            except Exception as error:
                return _response(
                    "run_portfolio",
                    VerificationStatus.ERROR,
                    authority=VerificationAuthority.NONE,
                    result={
                        "plan": plan_dict,
                        "capability_gaps": gaps,
                        "attempt_count": len(getattr(plan, "attempts", ()) or ()),
                        "executed": True,
                    },
                    diagnostics=(f"{type(error).__name__}: {error}",),
                    request_id=request_id or portfolio_obligation.obligation_id,
                    property_id=portfolio_obligation.obligation_id,
                    cache=_empty_cache(source="portfolio_execution"),
                )

        outcome_payloads = []
        for item in executed_outcomes:
            if hasattr(item, "to_dict"):
                outcome_payloads.append(item.to_dict())
            elif isinstance(item, Mapping):
                outcome_payloads.append(dict(item))
            else:
                outcome_payloads.append({"outcome": str(item)})

        result: dict[str, Any] = {
            "plan": plan_dict,
            "capability_gaps": gaps,
            "attempt_count": len(getattr(plan, "attempts", ()) or ()),
            "executed": bool(execute or outcomes is not None),
            "executable_provider_matrix": EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
        }
        if selection_dict is not None:
            result["selection"] = selection_dict
            result["verdict"] = selection_dict.get("verdict", "")
            result["quarantined_attempt_ids"] = list(
                selection_dict.get("quarantined_attempt_ids") or ()
            )
            result["disagreement"] = bool(selection_dict.get("disagreement"))
        if outcome_payloads:
            result["outcomes"] = outcome_payloads

        return _response(
            "run_portfolio",
            status,
            authority=selection_authority,
            result=result,
            assumptions=tuple(portfolio_obligation.assumption_ids),
            bounds=policy.to_dict() if hasattr(policy, "to_dict") else {},
            unsupported_features=unsupported,
            request_id=request_id or portfolio_obligation.obligation_id,
            property_id=portfolio_obligation.obligation_id,
            cache=_empty_cache(source=cache_source),
        )

    def _execute_portfolio_attempts(
        self,
        plan: Any,
        portfolio_obligation: Any,
        *,
        registry: Any,
    ) -> list[Any]:
        """Dispatch each planned attempt through the registry when runnable."""

        from ipfs_datasets_py.logic.backends.portfolio import (
            PortfolioAttemptOutcome,
            PortfolioRole,
        )
        from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
        from ipfs_datasets_py.logic.families.models import EvidenceAuthority
        from ipfs_datasets_py.logic.ir_core.claims import FrozenMap as _FrozenMap
        from ipfs_datasets_py.logic.ir_core.protocols import (
            BackendRequest,
            ExecutionBounds,
            QueryKind,
        )

        outcomes: list[Any] = []
        bounds = getattr(getattr(plan, "resource_policy", None), "bounds", None)
        if not isinstance(bounds, ExecutionBounds):
            bounds = ExecutionBounds()
        statement = str(getattr(portfolio_obligation, "statement", "") or "true")
        claim_digest = stable_digest(
            {
                "claim_id": f"claim:{portfolio_obligation.obligation_id}",
                "statement": statement,
            }
        )
        obligation_digest = stable_digest(
            {
                "obligation_id": portfolio_obligation.obligation_id,
                "statement": statement,
            }
        )
        assumption_ids = tuple(getattr(portfolio_obligation, "assumption_ids", ()) or ())

        for spec in getattr(plan, "attempts", ()) or ():
            backend_id = str(spec.backend_id)
            role = getattr(spec, "role", PortfolioRole.AUTHORITY)
            authority = getattr(spec, "result_authority", ResultAuthority.SATISFIABILITY)
            stage = int(getattr(spec, "stage", 0) or 0)
            runnable = bool(getattr(spec, "runnable", True))
            if not runnable:
                outcomes.append(
                    PortfolioAttemptOutcome(
                        attempt_id=spec.attempt_id,
                        backend_id=backend_id,
                        status=ResultStatus.UNAVAILABLE,
                        authority=authority,
                        role=role,
                        stage=stage,
                        detail=getattr(spec, "gap_reason", "") or "capability gap",
                        achieved_assurance=EvidenceAuthority.NONE,
                    )
                )
                continue

            registered = backend_id in set(registry)
            if not registered:
                outcomes.append(
                    PortfolioAttemptOutcome(
                        attempt_id=spec.attempt_id,
                        backend_id=backend_id,
                        status=ResultStatus.UNAVAILABLE,
                        authority=authority,
                        role=role,
                        stage=stage,
                        detail=f"backend {backend_id!r} is not registered",
                        achieved_assurance=EvidenceAuthority.NONE,
                    )
                )
                continue

            try:
                available = registry.is_available(backend_id)
            except Exception:
                available = False
            if not available:
                outcomes.append(
                    PortfolioAttemptOutcome(
                        attempt_id=spec.attempt_id,
                        backend_id=backend_id,
                        status=ResultStatus.UNAVAILABLE,
                        authority=authority,
                        role=role,
                        stage=stage,
                        detail=f"backend {backend_id!r} is unavailable",
                        achieved_assurance=EvidenceAuthority.NONE,
                    )
                )
                continue

            # Map portfolio family to a compatible query kind for the shared protocol.
            family = getattr(spec, "family", None)
            family_value = getattr(family, "value", str(family or "solver"))
            query_kind = QueryKind.SATISFIABILITY
            logic_family = "first_order"
            if family_value == "monitor":
                query_kind = QueryKind.RUNTIME_MONITOR
                logic_family = "temporal"
            elif family_value == "policy":
                query_kind = QueryKind.POLICY_APPROVAL
                logic_family = "authorization"
            elif family_value in {"atp", "kernel", "orchestrator", "hyperproperty", "protocol"}:
                query_kind = QueryKind.THEOREM_PROOF
                if family_value == "hyperproperty":
                    logic_family = "hyperproperty"
                elif family_value == "protocol":
                    logic_family = "protocol"
                elif family_value == "kernel":
                    logic_family = "software_verification"
            elif family_value == "model_checker":
                logic_family = "state_transition"

            request = BackendRequest(
                request_id=f"req:portfolio:{spec.attempt_id}",
                claim_id=f"claim:{portfolio_obligation.obligation_id}",
                declaration_id=f"decl:{portfolio_obligation.obligation_id}",
                claim_digest=claim_digest,
                obligation_id=str(portfolio_obligation.obligation_id),
                obligation_digest=obligation_digest,
                assumption_ids=assumption_ids,
                logic_family=logic_family,
                query_kind=query_kind,
                bounds=bounds,
                payload=_FrozenMap(
                    {
                        "statement": statement,
                        "encoding": "smtlib2",
                        "source": f"(assert true)\n(check-sat)\n",
                        "formula": statement,
                        "goal": statement,
                    }
                ),
                requested_backend_id=backend_id,
            )

            try:
                attempt, result = registry.run(request, backend_id=backend_id)
            except Exception as error:
                outcomes.append(
                    PortfolioAttemptOutcome(
                        attempt_id=spec.attempt_id,
                        backend_id=backend_id,
                        status=ResultStatus.ERROR,
                        authority=authority,
                        role=role,
                        stage=stage,
                        detail=f"{type(error).__name__}: {error}",
                        achieved_assurance=EvidenceAuthority.NONE,
                    )
                )
                continue

            raw_status = getattr(result, "status", ResultStatus.UNKNOWN)
            status_token = getattr(raw_status, "value", raw_status)
            try:
                result_status = (
                    raw_status
                    if isinstance(raw_status, ResultStatus)
                    else ResultStatus(str(status_token))
                )
            except ValueError:
                result_status = ResultStatus.UNKNOWN
            attempt_status = getattr(attempt, "status", None)
            attempt_status_value = getattr(attempt_status, "value", str(attempt_status or ""))
            if attempt_status_value == "unavailable":
                result_status = ResultStatus.UNAVAILABLE

            conclusive_counterexample = result_status in {
                ResultStatus.SATISFIABLE,
                ResultStatus.DISPROVED,
                ResultStatus.VIOLATED,
                ResultStatus.DENIED,
                ResultStatus.ATTACK_FOUND,
            }
            achieved = EvidenceAuthority.BOUNDED
            if result_status in {ResultStatus.CANDIDATE}:
                achieved = EvidenceAuthority.ADVISORY
            if result_status in {
                ResultStatus.UNKNOWN,
                ResultStatus.UNAVAILABLE,
                ResultStatus.ERROR,
                ResultStatus.TIMEOUT,
                ResultStatus.UNSUPPORTED,
                ResultStatus.MALFORMED,
            }:
                achieved = EvidenceAuthority.NONE

            diagnostics = tuple(getattr(attempt, "diagnostics", ()) or ())
            detail = "; ".join(diagnostics) if diagnostics else ""
            outcomes.append(
                PortfolioAttemptOutcome(
                    attempt_id=spec.attempt_id,
                    backend_id=backend_id,
                    status=result_status,
                    authority=authority,
                    role=role,
                    stage=stage,
                    conclusive_counterexample=conclusive_counterexample,
                    achieved_assurance=achieved,
                    detail=detail,
                )
            )
        return outcomes

    # ── Counterexamples ───────────────────────────────────────────────────

    def explain_counterexample(
        self,
        witness: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        violated_property: str = "",
        assumption_ids: Sequence[str] = (),
        finite_bounds: Mapping[str, Any] | None = None,
        bindings: Mapping[str, Any] | None = None,
        private_store: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> VerificationResponse:
        """Project a counterexample through the secret-safe public boundary.

        Raw provider output, hidden witnesses, credentials, source blobs, and
        private channels never appear in ``result`` or ``witnesses``.  The
        response carries :class:`CounterexampleEnvelope@2` only; private
        material is referenced by digest/retention metadata when present.
        """

        request_id = _text(request_id, "request_id", optional=True)
        if witness is None:
            return _response(
                "explain_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("witness is required",),
                request_id=request_id,
            )

        from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
            COUNTEREXAMPLE_ENVELOPE_INTERFACE,
            PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE,
            CounterexampleBoundaryError,
            project_public_counterexample,
        )

        try:
            envelope = project_public_counterexample(
                witness,
                violated_property=violated_property,
                assumption_ids=assumption_ids,
                finite_bounds=finite_bounds,
                bindings=bindings,
                private_store=private_store,
            )
        except CounterexampleBoundaryError as exc:
            return _response(
                "explain_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )

        public = envelope.to_public_dict()
        # Explicitly refuse residual raw channels on the API surface.
        public.pop("raw", None)
        public["boundary"] = PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE
        public["envelope_interface"] = COUNTEREXAMPLE_ENVELOPE_INTERFACE
        # Kind-derived authority remains on the envelope; the stable API
        # operation itself is a bounded public projection (never escalated).

        return _response(
            "explain_counterexample",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.BOUNDED,
            result=public,
            assumptions=envelope.assumptions,
            bounds=dict(envelope.bounds),
            witnesses=(envelope.to_witness_dict(),),
            request_id=request_id,
            property_id=envelope.violated_property,
            provider_id=envelope.tool_id,
            cache=_empty_cache(source="counterexample_public_boundary"),
        )

    # ── Receipts (VerifiedReceiptDispatch@2 / AttestationAuthorityBoundary@2) ─

    def verify_receipt(
        self,
        receipt: Any,
        expectation: Any | None = None,
        *,
        request_id: str = "",
    ) -> VerificationResponse:
        """Validate a typed receipt via closed schema dispatch.

        Empty, unknown-schema, forged-kernel, stale, wrong-tree/property/
        assumption/bound/tool, and cross-authority inputs are rejected.
        Authority is never upgraded past the receipt's declared ceiling.
        """

        request_id = _text(request_id, "request_id", optional=True)
        if receipt is None:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                unsupported_features=("receipt",),
                diagnostics=("receipt is required",),
                result={
                    "valid": False,
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "empty",
                },
                request_id=request_id,
            )

        try:
            payload = _receipt_payload(receipt)
        except VerificationAPIError as error:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(error),),
                result={
                    "valid": False,
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "malformed",
                },
                request_id=request_id,
            )

        if not payload:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("empty receipt payload is rejected",),
                result={
                    "valid": False,
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "empty",
                },
                request_id=request_id,
            )

        schema_version = _schema_version_of(payload, receipt)
        kind = _dispatch_receipt_kind(schema_version)
        if not kind:
            # Reject permissive structural accept of bare authority/kernel claims.
            forged_kernel = str(payload.get("authority", "")).lower() in {
                "theorem",
                "kernel",
            } or str(payload.get("kind", "")).lower() in {
                "kernel",
                "kernel_receipt",
                "forged_kernel",
            }
            reason = "forged-kernel" if forged_kernel else "unknown"
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    "unknown or missing receipt schema_version; "
                    f"closed dispatch accepts only {sorted(CLOSED_RECEIPT_SCHEMAS)}",
                ),
                result={
                    "valid": False,
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": reason,
                    "schema_version": schema_version or None,
                    "claimed_authority": payload.get("authority"),
                },
                request_id=request_id,
            )

        if kind == "translation":
            return self._verify_translation_receipt(
                receipt,
                payload,
                expectation,
                request_id=request_id,
            )
        return self._verify_trusted_proof_receipt(
            receipt,
            payload,
            expectation,
            request_id=request_id,
        )

    def _verify_translation_receipt(
        self,
        receipt: Any,
        payload: Mapping[str, Any],
        expectation: Any | None,
        *,
        request_id: str,
    ) -> VerificationResponse:
        try:
            from ipfs_datasets_py.logic.software_verification.receipts import (
                LogicTranslationReceipt,
                TranslationReceiptExpectation,
                validate_translation_receipt,
            )
        except Exception as error:
            return _response(
                "verify_receipt",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("translation_receipt",),
                diagnostics=(
                    f"translation receipt module unavailable: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )

        try:
            if isinstance(receipt, LogicTranslationReceipt):
                typed = receipt
            else:
                typed = LogicTranslationReceipt.from_dict(payload)
        except Exception as error:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                result={
                    "valid": False,
                    "kind": "translation_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "schema_reject",
                },
                request_id=request_id,
            )

        authority = _evidence_to_verification_authority(typed.authority_ceiling)
        result_body: dict[str, Any] = {
            "valid": True,
            "kind": "translation_receipt",
            "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
            "schema_version": typed.schema_version,
            "receipt_id": typed.receipt_id,
            "digest": typed.receipt_id,
            "authority_ceiling": typed.authority_ceiling.value,
            "round_trip": typed.to_dict(),
        }

        if expectation is None:
            return _response(
                "verify_receipt",
                VerificationStatus.SUCCEEDED,
                authority=authority,
                result=result_body,
                assumptions=typed.assumptions,
                request_id=request_id,
                cache=_empty_cache(source="receipt_validation"),
            )

        try:
            if isinstance(expectation, TranslationReceiptExpectation):
                typed_expectation = expectation
            elif isinstance(expectation, Mapping):
                typed_expectation = TranslationReceiptExpectation.from_dict(expectation)
            else:
                raise VerificationAPIError(
                    "translation receipt expectation must be "
                    "TranslationReceiptExpectation or mapping"
                )
            validation = validate_translation_receipt(typed, typed_expectation)
        except Exception as error:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                result={
                    "valid": False,
                    "kind": "translation_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "expectation_reject",
                },
                request_id=request_id,
            )

        validation_dict = (
            validation.to_dict()
            if hasattr(validation, "to_dict")
            else {"validation": str(validation)}
        )
        ok = bool(getattr(validation, "current", False))
        effective = getattr(validation, "effective_authority_ceiling", None)
        effective_authority = (
            _evidence_to_verification_authority(effective) if ok else VerificationAuthority.NONE
        )
        issues = [
            getattr(issue, "code", issue).value
            if hasattr(getattr(issue, "code", issue), "value")
            else str(getattr(issue, "code", issue))
            for issue in getattr(validation, "issues", ())
        ]
        result_body.update(
            {
                "valid": ok,
                "validation": validation_dict,
                "issues": issues,
                "reason": None if ok else "stale_or_mismatched_binding",
            }
        )
        return _response(
            "verify_receipt",
            VerificationStatus.SUCCEEDED if ok else VerificationStatus.INVALID,
            authority=effective_authority,
            result=result_body,
            assumptions=typed.assumptions,
            diagnostics=tuple(issues) if issues else (),
            request_id=request_id,
            cache=_empty_cache(source="receipt_validation"),
        )

    def _verify_trusted_proof_receipt(
        self,
        receipt: Any,
        payload: Mapping[str, Any],
        expectation: Any | None,
        *,
        request_id: str,
    ) -> VerificationResponse:
        try:
            from ipfs_datasets_py.logic.bridge.proof_receipt_attestation import (
                TrustedProofReceipt,
            )
            from ipfs_datasets_py.logic.backends.results import ResultAuthority
            from ipfs_datasets_py.logic.families.models import EvidenceAuthority
        except Exception as error:
            return _response(
                "verify_receipt",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("trusted_proof_receipt",),
                diagnostics=(
                    f"trusted proof receipt module unavailable: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )

        try:
            if isinstance(receipt, TrustedProofReceipt):
                typed = receipt
            else:
                typed = TrustedProofReceipt.from_dict(payload)
        except Exception as error:
            message = str(error)
            reason = "schema_reject"
            lowered = message.lower()
            if "attestation" in lowered and "underlying" in lowered:
                reason = "cross-authority"
            elif "not eligible" in lowered or "not conclusive" in lowered:
                reason = "forged-kernel"
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                result={
                    "valid": False,
                    "kind": "trusted_proof_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": reason,
                },
                request_id=request_id,
            )

        # Independent checker evidence is mandatory for theorem-class authority.
        checker_ok = True
        checker_diagnostics: list[str] = []
        if typed.underlying_authority is ResultAuthority.THEOREM:
            ceiling = typed.translation_ceiling
            if ceiling is EvidenceAuthority.NONE or ceiling is EvidenceAuthority.ADVISORY:
                checker_ok = False
                checker_diagnostics.append(
                    "forged-kernel: theorem authority requires independent checker "
                    f"evidence (translation_ceiling={ceiling.value!r})"
                )
            if not typed.source_result_digest:
                checker_ok = False
                checker_diagnostics.append(
                    "forged-kernel: theorem authority requires source_result_digest"
                )

        if not checker_ok:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=tuple(checker_diagnostics),
                result={
                    "valid": False,
                    "kind": "trusted_proof_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "forged-kernel",
                    "receipt_id": typed.receipt_id,
                },
                request_id=request_id,
            )

        authority = _result_to_verification_authority(typed.underlying_authority)
        result_body: dict[str, Any] = {
            "valid": True,
            "kind": "trusted_proof_receipt",
            "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
            "schema_version": typed.schema_version,
            "receipt_id": typed.receipt_id,
            "content_id": typed.content_id,
            "digest": typed.content_id,
            "underlying_authority": typed.underlying_authority.value,
            "underlying_status": typed.underlying_status.value,
            "tree_id": typed.tree_id,
            "property_id": typed.property_id,
            "backend_id": typed.backend_id,
            "source_result_digest": typed.source_result_digest,
            "translation_ceiling": typed.translation_ceiling.value,
            "round_trip": typed.to_dict(),
        }

        if expectation is None:
            return _response(
                "verify_receipt",
                VerificationStatus.SUCCEEDED,
                authority=authority,
                result=result_body,
                assumptions=typed.assumptions,
                property_id=typed.property_id,
                provider_id=typed.backend_id,
                request_id=request_id,
                cache=_empty_cache(source="receipt_validation"),
            )

        if not isinstance(expectation, Mapping):
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    "trusted proof receipt expectation must be a binding mapping",
                ),
                result={
                    "valid": False,
                    "kind": "trusted_proof_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "expectation_reject",
                },
                request_id=request_id,
            )

        try:
            issues = _trusted_binding_issues(typed, dict(expectation))
        except VerificationAPIError as error:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(error),),
                result={
                    "valid": False,
                    "kind": "trusted_proof_receipt",
                    "dispatch": VERIFIED_RECEIPT_DISPATCH_INTERFACE,
                    "reason": "expectation_reject",
                },
                request_id=request_id,
            )

        if issues:
            return _response(
                "verify_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=tuple(issues),
                result={
                    **result_body,
                    "valid": False,
                    "issues": issues,
                    "reason": "binding_mismatch",
                },
                assumptions=typed.assumptions,
                property_id=typed.property_id,
                provider_id=typed.backend_id,
                request_id=request_id,
                cache=_empty_cache(source="receipt_validation"),
            )

        return _response(
            "verify_receipt",
            VerificationStatus.SUCCEEDED,
            authority=authority,
            result=result_body,
            assumptions=typed.assumptions,
            property_id=typed.property_id,
            provider_id=typed.backend_id,
            request_id=request_id,
            cache=_empty_cache(source="receipt_validation"),
        )

    def attest_receipt(
        self,
        receipt: Any,
        *,
        backend_policy: Any | None = None,
        witness: Any | None = None,
        issued_at: str = "",
        expires_at: str = "",
        backend_mode: str = "disabled",
        request_id: str = "",
    ) -> VerificationResponse:
        """Prepare a ZKP attestation envelope for a trusted proof receipt.

        Attestation is orthogonal to theorem authority
        (:data:`ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE`).  Prepared and
        simulated envelopes never report proof success and never upgrade the
        underlying semantic authority.
        """

        request_id = _text(request_id, "request_id", optional=True)
        try:
            from ipfs_datasets_py.logic.bridge.proof_receipt_attestation import (
                AttestationBackendMode,
                AttestationBackendPolicy,
                PrivateWitness,
                TrustedProofReceipt,
                prepare_receipt_attestation,
                create_attestation_envelope,
            )
        except Exception as error:
            return _response(
                "attest_receipt",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("proof_receipt_attestation",),
                diagnostics=(
                    f"attestation module unavailable: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )

        if receipt is None:
            return _response(
                "attest_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("receipt is required",),
                result={
                    "proof_success": False,
                    "authoritative": False,
                    "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
                },
                request_id=request_id,
            )

        mode_raw = str(getattr(backend_mode, "value", backend_mode) or "").strip().lower()
        mode_enum: Any | None
        try:
            if isinstance(backend_mode, AttestationBackendMode):
                mode_enum = backend_mode
            elif mode_raw in {"disabled", "none", ""}:
                mode_enum = None
            else:
                mode_enum = AttestationBackendMode(mode_raw)
            mode = (
                mode_enum.value
                if mode_enum is not None
                else (mode_raw or "disabled")
            )
        except Exception:
            mode_enum = None
            mode = mode_raw or str(backend_mode)

        if mode in {"disabled", "none", ""} or mode_enum is None and mode_raw in {
            "disabled",
            "none",
            "",
        }:
            return _response(
                "attest_receipt",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.ATTESTATION,
                result={
                    "backend_mode": mode or "disabled",
                    "proof_success": False,
                    "authoritative": False,
                    "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
                },
                unsupported_features=("attestation_backend",),
                diagnostics=(
                    "attestation backend is disabled; pass an explicit non-disabled backend_mode",
                ),
                request_id=request_id,
            )

        if mode_enum is None:
            return _response(
                "attest_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    f"backend_mode {mode!r} is not a recognized AttestationBackendMode",
                ),
                result={
                    "backend_mode": mode,
                    "proof_success": False,
                    "authoritative": False,
                    "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
                },
                request_id=request_id,
            )

        if not issued_at or not expires_at:
            return _response(
                "attest_receipt",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("issued_at and expires_at are required for attestation",),
                result={
                    "proof_success": False,
                    "authoritative": False,
                    "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
                },
                request_id=request_id,
            )

        try:
            if isinstance(receipt, TrustedProofReceipt):
                typed_receipt = receipt
            elif isinstance(receipt, Mapping) or hasattr(receipt, "to_dict"):
                payload = _receipt_payload(receipt)
                typed_receipt = TrustedProofReceipt.from_dict(payload)
            else:
                raise VerificationAPIError(
                    "receipt must be a TrustedProofReceipt or trusted-proof-receipt/v1 mapping"
                )

            if isinstance(backend_policy, AttestationBackendPolicy):
                policy = backend_policy
            elif isinstance(backend_policy, Mapping):
                policy = AttestationBackendPolicy.from_dict(backend_policy)
            elif backend_policy is None:
                raise VerificationAPIError(
                    "backend_policy is required for non-disabled attestation"
                )
            else:
                policy = backend_policy

            # Align policy mode with the explicit facade backend_mode.
            if (
                hasattr(policy, "backend_mode")
                and policy.backend_mode is not mode_enum
            ):
                policy = AttestationBackendPolicy(
                    backend_id=policy.backend_id,
                    backend_version=policy.backend_version,
                    circuit_id=policy.circuit_id,
                    circuit_version=policy.circuit_version,
                    ceremony_id=policy.ceremony_id,
                    crs_id=policy.crs_id,
                    proving_key_id=policy.proving_key_id,
                    verification_key_id=policy.verification_key_id,
                    revocation_policy_id=policy.revocation_policy_id,
                    backend_mode=mode_enum,
                    verification_key_expires_at=policy.verification_key_expires_at,
                )

            if isinstance(witness, PrivateWitness):
                private_witness = witness
            elif isinstance(witness, Mapping) and witness:
                private_witness = PrivateWitness(witness)
            elif witness is None:
                # Preparation-only path: no secret material is admitted.
                private_witness = PrivateWitness({"_prepared_placeholder": True})
            else:
                raise VerificationAPIError(
                    "witness must be a PrivateWitness, mapping, or omitted"
                )

            attestation_request = prepare_receipt_attestation(
                typed_receipt,
                backend_policy=policy,
                witness=private_witness,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            envelope = create_attestation_envelope(
                attestation_request,
                backend_mode=mode_enum,
                proof_artifact_id=f"artifact:{request_id or 'facade'}",
                proof_digest=stable_digest(
                    {
                        "request_id": request_id,
                        "issued_at": issued_at,
                        "receipt_id": typed_receipt.receipt_id,
                    }
                ),
            )
        except Exception as error:
            return _response(
                "attest_receipt",
                VerificationStatus.ERROR
                if not isinstance(error, VerificationAPIError)
                else VerificationStatus.INVALID,
                authority=VerificationAuthority.ATTESTATION,
                diagnostics=(f"{type(error).__name__}: {error}",),
                result={
                    "proof_success": False,
                    "authoritative": False,
                    "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
                },
                request_id=request_id,
            )

        envelope_dict = (
            envelope.to_dict() if hasattr(envelope, "to_dict") else {"envelope": str(envelope)}
        )
        simulated = mode_enum is AttestationBackendMode.SIMULATED or bool(
            getattr(envelope, "simulated", False)
        )
        # Envelope generation is preparation, never independent proof success.
        proof_success = False
        authoritative = bool(getattr(envelope, "authoritative", False))
        status = (
            VerificationStatus.PARTIAL if simulated else VerificationStatus.SUCCEEDED
        )
        diagnostics: tuple[str, ...] = ()
        if simulated:
            diagnostics = (
                "simulated attestation is preparation-only and cannot report proof success",
            )
        elif not authoritative:
            diagnostics = (
                "prepared attestation envelope is not independent verification; "
                "proof_success remains false",
            )

        underlying_authority = typed_receipt.underlying_authority.value
        underlying_status = typed_receipt.underlying_status.value
        return _response(
            "attest_receipt",
            status,
            authority=VerificationAuthority.ATTESTATION,
            result={
                "envelope": envelope_dict,
                "backend_mode": mode_enum.value,
                "proof_success": proof_success,
                "authoritative": authoritative,
                "prepared": True,
                "simulated": simulated,
                "underlying_authority": underlying_authority,
                "underlying_status": underlying_status,
                "boundary": ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
            },
            assumptions=typed_receipt.assumptions,
            property_id=typed_receipt.property_id,
            provider_id=typed_receipt.backend_id,
            diagnostics=diagnostics,
            request_id=request_id,
            cache=_empty_cache(source="attestation"),
        )

    # ── Advisor ───────────────────────────────────────────────────────────

    def advise(
        self,
        request: Mapping[str, Any] | Any,
        *,
        provider: str = "static",
        request_id: str = "",
    ) -> VerificationResponse:
        """Produce untrusted formalization proposals (never proof authority)."""

        request_id = _text(request_id, "request_id", optional=True)
        provider = _text(provider, "provider")
        try:
            from ipfs_datasets_py.logic.formalization.proposal_advisors import (
                LEANSTRAL_ADVISOR_ID,
                SYMAI_ADVISOR_ID,
                LeanstralProposalAdvisor,
                ProposalAdvisorRequest,
                ProposalKind,
                StaticProposalModel,
                SymAIProposalAdvisor,
            )
        except Exception as error:
            return _response(
                "advise",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("proposal_advisors",),
                diagnostics=(f"advisor module unavailable: {type(error).__name__}: {error}",),
                request_id=request_id,
                provider_id=provider,
            )

        try:
            if isinstance(request, ProposalAdvisorRequest):
                advisor_request = request
            elif isinstance(request, Mapping):
                payload = dict(request)
                kind = payload.get("kind", ProposalKind.LEMMA)
                if not isinstance(kind, ProposalKind):
                    kind = ProposalKind(kind)
                goal_text = str(
                    payload.get("goal_text") or payload.get("statement") or "unspecified goal"
                )
                context_text = str(
                    payload.get("context_text") or payload.get("context") or goal_text
                )
                advisor_request = ProposalAdvisorRequest(
                    request_id=str(payload.get("request_id") or request_id or "adv:facade"),
                    goal_id=str(payload.get("goal_id") or "goal:facade"),
                    logic_family=str(payload.get("logic_family") or "first_order"),
                    kind=kind,
                    source_ref_ids=tuple(payload.get("source_ref_ids") or ("src:facade",)),
                    context_text=context_text,
                    goal_text=goal_text,
                    formula_id=str(payload.get("formula_id") or ""),
                    notes=str(payload.get("notes") or ""),
                )
            else:
                raise VerificationAPIError("request must be ProposalAdvisorRequest or mapping")

            static_model = StaticProposalModel(response='{"candidates":[]}')
            if provider in {LEANSTRAL_ADVISOR_ID, "leanstral", "static"}:
                advisor = LeanstralProposalAdvisor(model=static_model)
                provider_id = (
                    LEANSTRAL_ADVISOR_ID if provider != "static" else "static"
                )
            elif provider in {SYMAI_ADVISOR_ID, "symai", "sym_ai"}:
                advisor = SymAIProposalAdvisor(model=static_model)
                provider_id = SYMAI_ADVISOR_ID
            else:
                return _response(
                    "advise",
                    VerificationStatus.UNSUPPORTED,
                    authority=VerificationAuthority.ADVISORY,
                    result={"provider": provider},
                    unsupported_features=(f"advisor:{provider}",),
                    diagnostics=(f"advisor provider {provider!r} is not declared",),
                    request_id=request_id,
                    provider_id=provider,
                )
            result = advisor.propose(advisor_request)
        except Exception as error:
            return _response(
                "advise",
                VerificationStatus.INVALID
                if isinstance(error, (VerificationAPIError, TypeError, ValueError))
                else VerificationStatus.ERROR,
                authority=VerificationAuthority.ADVISORY,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
                provider_id=provider,
            )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
        candidates = []
        if hasattr(result, "candidates"):
            candidates = [
                item.to_dict() if hasattr(item, "to_dict") else str(item)
                for item in result.candidates
            ]
        return _response(
            "advise",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.ADVISORY,
            result={
                "provider_id": provider_id,
                "candidates": candidates,
                "proposal": result_dict,
                "authority_note": "Advisor output is never proof evidence.",
            },
            request_id=request_id or advisor_request.request_id,
            provider_id=provider_id,
            cache=_empty_cache(source="advisor"),
        )

    # ── Opt-in probe / install ────────────────────────────────────────────

    def probe_provider(
        self,
        provider_id: str,
        *,
        request_id: str = "",
    ) -> VerificationResponse:
        """Explicit availability probe for one registered backend."""

        provider_id = _text(provider_id, "provider_id")
        request_id = _text(request_id, "request_id", optional=True)
        registry = self._registry()
        # ProofBackendRegistry.__contains__ routes through __getitem__ and
        # raises UnknownBackendError; compare against the key view instead.
        if provider_id not in set(registry):
            return _response(
                "probe_provider",
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                result={"provider_id": provider_id, "available": False},
                unsupported_features=(f"provider:{provider_id}",),
                diagnostics=(f"provider {provider_id!r} is not registered",),
                request_id=request_id,
                provider_id=provider_id,
            )
        try:
            available = bool(registry.is_available(provider_id))
        except Exception as error:
            return _response(
                "probe_provider",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                result={"provider_id": provider_id, "available": False},
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
                provider_id=provider_id,
            )
        return _response(
            "probe_provider",
            VerificationStatus.SUCCEEDED if available else VerificationStatus.UNAVAILABLE,
            authority=VerificationAuthority.NONE,
            result={
                "provider_id": provider_id,
                "available": available,
                "availability": (
                    FeatureAvailability.AVAILABLE.value
                    if available
                    else FeatureAvailability.UNAVAILABLE.value
                ),
            },
            request_id=request_id,
            provider_id=provider_id,
            cache=_empty_cache(source="probe"),
        )

    def install_provider(
        self,
        provider_id: str,
        *,
        request_id: str = "",
        allow_install: bool = False,
    ) -> VerificationResponse:
        """Opt-in installer hook.

        Installation is never performed by default.  Callers must pass
        ``allow_install=True``; even then this facade only reports the
        install pathway and does not mutate the environment unless a bound
        installer is injected in a future revision.
        """

        provider_id = _text(provider_id, "provider_id")
        request_id = _text(request_id, "request_id", optional=True)
        if not allow_install:
            return _response(
                "install_provider",
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                result={"provider_id": provider_id, "installed": False},
                unsupported_features=("install_without_opt_in",),
                diagnostics=(
                    "install_provider requires allow_install=True; "
                    "discovery never installs providers",
                ),
                request_id=request_id,
                provider_id=provider_id,
            )
        # Fail closed: the stable facade does not perform installs itself.
        return _response(
            "install_provider",
            VerificationStatus.UNAVAILABLE,
            authority=VerificationAuthority.NONE,
            result={
                "provider_id": provider_id,
                "installed": False,
                "reason": "installer_not_bound_in_facade",
            },
            unsupported_features=("provider_installer",),
            diagnostics=(
                "no installer is bound to LogicVerificationAPI; "
                "use the toolchain installer surface explicitly",
            ),
            request_id=request_id,
            provider_id=provider_id,
        )

    # ── GoalTacticianAPI@1 (FVT-G050) ─────────────────────────────────────

    def list_goal_tactician_operations(
        self,
        *,
        request_id: str = "",
    ) -> VerificationResponse:
        """Declarative catalog of GoalTacticianAPI@1 operations and channels."""

        request_id = _text(request_id, "request_id", optional=True)
        surface = list_goal_tactician_cli_mcp_surface()
        return _response(
            "list_goal_tactician_operations",
            VerificationStatus.DECLARATIVE,
            authority=VerificationAuthority.DECLARATIVE,
            result=surface,
            request_id=request_id,
            cache=_empty_cache(source="goal_tactician_catalog"),
        )

    def formalize_goal(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Formalize a prose end goal into candidate-only end-goal structures.

        Never admits a goal and never upgrades transport success to proof
        authority.  Supervisor-only mutation controls are rejected.
        """

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "formalize_goal",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True, "admitted": False},
                diagnostics=("cancelled before formalization",),
                request_id=request_id,
            )
        if request is None:
            return _response(
                "formalize_goal",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request is required",),
                request_id=request_id,
            )
        payload = request if isinstance(request, Mapping) else None
        if payload is not None:
            forbidden = _reject_forbidden_controls(payload, "formalize_goal")
            if forbidden:
                return _response(
                    "formalize_goal",
                    VerificationStatus.INVALID,
                    authority=VerificationAuthority.NONE,
                    diagnostics=(forbidden,),
                    unsupported_features=("supervisor_only_control",),
                    request_id=request_id,
                )
        try:
            from ipfs_datasets_py.logic.software_verification.tactician.end_goal_formalizer import (
                END_GOAL_FORMALIZER_INTERFACE,
                EndGoalFormalizer,
                EndGoalFormalizerError,
                EndGoalFormalizerRequest,
                FormalizationStatus,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "formalize_goal",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"formalizer import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        try:
            if isinstance(request, EndGoalFormalizerRequest):
                formalizer_request = request
            elif isinstance(request, Mapping):
                formalizer_request = EndGoalFormalizerRequest.from_dict(request)
            else:
                raise EndGoalFormalizerError(
                    "request must be EndGoalFormalizerRequest or mapping"
                )
            result = EndGoalFormalizer().formalize(formalizer_request)
        except EndGoalFormalizerError as exc:
            return _response(
                "formalize_goal",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "formalize_goal",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        status_map = {
            FormalizationStatus.CANDIDATE: VerificationStatus.SUCCEEDED,
            FormalizationStatus.UNDERSPECIFIED: VerificationStatus.PARTIAL,
            FormalizationStatus.UNSUPPORTED: VerificationStatus.UNSUPPORTED,
            FormalizationStatus.REJECTED: VerificationStatus.INVALID,
            FormalizationStatus.ERROR: VerificationStatus.ERROR,
        }
        public = _redact_public_mapping(result.to_dict())
        public["admitted"] = False
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["formalizer_interface"] = END_GOAL_FORMALIZER_INTERFACE
        public["proof_success"] = False
        return _response(
            "formalize_goal",
            status_map.get(result.status, VerificationStatus.PARTIAL),
            authority=VerificationAuthority.ADVISORY,
            result=public,
            bounds=_normalize_bounds(getattr(formalizer_request, "bounds", None)),
            request_id=request_id,
            cache=_empty_cache(source="end_goal_formalizer"),
        )

    def compare_interpretations(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Compare goal interpretations or expose material ambiguity.

        Accepts either:
        * ``{"left": ..., "right": ...}`` for pairwise comparison; or
        * ``{"source": end_goal|prompt, "goal_id": ...}`` for ambiguity exposure.
        """

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "compare_interpretations",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True},
                diagnostics=("cancelled before interpretation comparison",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "compare_interpretations",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "compare_interpretations")
        if forbidden:
            return _response(
                "compare_interpretations",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.software_verification.tactician.ambiguity import (
                GOAL_AMBIGUITY_GATE_INTERFACE,
                GoalAmbiguityError,
                compare_goal_interpretations,
                expose_ambiguity,
            )
            from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
                EndGoalInterpretation,
                EndGoalSpec,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "compare_interpretations",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"ambiguity import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

        try:
            if "left" in request and "right" in request:
                left_raw = request["left"]
                right_raw = request["right"]
                left = (
                    left_raw
                    if isinstance(left_raw, EndGoalInterpretation)
                    else EndGoalInterpretation.from_dict(left_raw)
                )
                right = (
                    right_raw
                    if isinstance(right_raw, EndGoalInterpretation)
                    else EndGoalInterpretation.from_dict(right_raw)
                )
                diff = compare_goal_interpretations(left, right)
                public = _redact_public_mapping(diff.to_dict())
                public["mode"] = "pairwise"
                public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
                public["proof_success"] = False
                return _response(
                    "compare_interpretations",
                    VerificationStatus.SUCCEEDED,
                    authority=VerificationAuthority.ADVISORY,
                    result=public,
                    request_id=request_id,
                    cache=_empty_cache(source="goal_ambiguity_gate"),
                )

            source = request.get("source", request.get("end_goal", request.get("prompt")))
            if source is None:
                return _response(
                    "compare_interpretations",
                    VerificationStatus.INVALID,
                    authority=VerificationAuthority.NONE,
                    diagnostics=(
                        "request requires left/right interpretations or source/end_goal/prompt",
                    ),
                    request_id=request_id,
                )
            goal_id = str(request.get("goal_id") or "goal:compare")
            max_candidates = int(request.get("max_candidates") or 8)
            if isinstance(source, Mapping) and (
                source.get("schema") or source.get("goal_id") or source.get("caller_text")
            ):
                try:
                    source = EndGoalSpec.from_dict(source)
                except Exception:
                    # Fall through: expose_ambiguity also accepts mappings via analyze paths
                    # when given as EndGoalSpec-like; convert best-effort text.
                    if "caller_text" in source:
                        source = str(source.get("caller_text") or "")
            report = expose_ambiguity(
                source,
                goal_id=goal_id,
                max_candidates=max_candidates,
            )
            public = _redact_public_mapping(report.to_dict())
            public["mode"] = "ambiguity_gate"
            public["admitted"] = False
            public["gate_interface"] = GOAL_AMBIGUITY_GATE_INTERFACE
            public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
            public["proof_success"] = False
            status = (
                VerificationStatus.PARTIAL
                if public.get("requires_selection")
                else VerificationStatus.SUCCEEDED
            )
            return _response(
                "compare_interpretations",
                status,
                authority=VerificationAuthority.ADVISORY,
                result=public,
                request_id=request_id,
                cache=_empty_cache(source="goal_ambiguity_gate"),
            )
        except GoalAmbiguityError as exc:
            return _response(
                "compare_interpretations",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "compare_interpretations",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

    def discover_missing_proofs(
        self,
        surface: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        require_source_spans: bool = True,
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Emit typed proof holes for a compilation surface (missing-proof discovery)."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "discover_missing_proofs",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True},
                diagnostics=("cancelled before missing-proof discovery",),
                request_id=request_id,
            )
        if surface is None:
            return _response(
                "discover_missing_proofs",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("surface is required",),
                request_id=request_id,
            )
        if isinstance(surface, Mapping):
            forbidden = _reject_forbidden_controls(surface, "discover_missing_proofs")
            if forbidden:
                return _response(
                    "discover_missing_proofs",
                    VerificationStatus.INVALID,
                    authority=VerificationAuthority.NONE,
                    diagnostics=(forbidden,),
                    unsupported_features=("supervisor_only_control",),
                    request_id=request_id,
                )
        try:
            from ipfs_datasets_py.logic.software_verification.tactician.proof_holes import (
                TYPED_PROOF_HOLE_EMITTER_INTERFACE,
                CompilationSurface,
                ProofHoleEmissionError,
                emit_typed_proof_holes,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "discover_missing_proofs",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"proof hole import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )
        try:
            if isinstance(surface, CompilationSurface):
                compiled = surface
            elif isinstance(surface, Mapping):
                compiled = CompilationSurface.from_dict(surface)
            else:
                raise ProofHoleEmissionError("surface must be CompilationSurface or mapping")
            emission = emit_typed_proof_holes(
                compiled, require_source_spans=bool(require_source_spans)
            )
        except ProofHoleEmissionError as exc:
            return _response(
                "discover_missing_proofs",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except TypeError as exc:
            return _response(
                "discover_missing_proofs",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "discover_missing_proofs",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(emission.to_dict())
        public["emitter_interface"] = TYPED_PROOF_HOLE_EMITTER_INTERFACE
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["proof_success"] = False
        public["count"] = len(public.get("holes") or ())
        public["missing_proof_count"] = len(public.get("missing_proof_hole_ids") or ())
        return _response(
            "discover_missing_proofs",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.ADVISORY,
            result=public,
            request_id=request_id,
            cache=_empty_cache(source="typed_proof_hole_emitter"),
        )

    def plan_proof(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Rank complete missing-proof plan alternatives (bounded, non-authoritative)."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "plan_proof",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True, "proof_success": False},
                diagnostics=("cancelled before proof planning",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "plan_proof",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping with alternatives",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "plan_proof")
        if forbidden:
            return _response(
                "plan_proof",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )
        alternatives = request.get("alternatives")
        if alternatives is None:
            return _response(
                "plan_proof",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("alternatives are required",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.software_verification.tactician.proof_plan import (
                GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE,
                ProofPlanError,
                rank_missing_proof_plans,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "plan_proof",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"proof plan import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )
        try:
            ranking = rank_missing_proof_plans(
                alternatives,
                policy=request.get("policy"),
                bounds=request.get("bounds"),
            )
        except ProofPlanError as exc:
            return _response(
                "plan_proof",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "plan_proof",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(ranking.to_dict())
        public["ranker_interface"] = GOAL_DIRECTED_PROOF_PLAN_RANKER_INTERFACE
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["proof_success"] = False
        public["proof_claimed"] = False
        status = (
            VerificationStatus.SUCCEEDED
            if ranking.selected is not None
            else VerificationStatus.PARTIAL
        )
        return _response(
            "plan_proof",
            status,
            authority=VerificationAuthority.ADVISORY,
            result=public,
            bounds=_normalize_bounds(request.get("bounds")),
            request_id=request_id,
            cache=_empty_cache(source="goal_directed_proof_plan_ranker"),
        )

    def validate_proof_candidate(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Independently validate a proof-gap candidate (never discharges by silence)."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "validate_proof_candidate",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True, "proof_success": False},
                diagnostics=("cancelled before candidate validation",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "validate_proof_candidate",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "validate_proof_candidate")
        if forbidden:
            return _response(
                "validate_proof_candidate",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )
        candidate = request.get("candidate")
        hole = request.get("hole")
        binding = request.get("binding")
        if candidate is None or hole is None or binding is None:
            return _response(
                "validate_proof_candidate",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("candidate, hole, and binding are required",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
                CandidateValidationError,
                validate_candidate,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "validate_proof_candidate",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    f"candidate validation import failed: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )
        try:
            outcome = validate_candidate(
                candidate,
                hole,
                binding,
                backends=tuple(request.get("backends") or ()),
                recipe=request.get("recipe"),
                expected_candidate_content_id=str(
                    request.get("expected_candidate_content_id") or ""
                ),
                expected_hole_content_id=str(request.get("expected_hole_content_id") or ""),
                proposed_provider_verdicts=request.get("proposed_provider_verdicts"),
                bounds=request.get("bounds"),
            )
        except CandidateValidationError as exc:
            return _response(
                "validate_proof_candidate",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "validate_proof_candidate",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(
            outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)
        )
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        # Transport-level success never becomes proof success.
        public["proof_success"] = False
        verdict = str(public.get("verdict") or public.get("status") or "").lower()
        status = VerificationStatus.SUCCEEDED
        if verdict in {"reject", "rejected", "invalid", "fail", "failed"}:
            status = VerificationStatus.INVALID
        elif verdict in {"quarantine", "partial", "inconclusive"}:
            status = VerificationStatus.PARTIAL
        return _response(
            "validate_proof_candidate",
            status,
            authority=VerificationAuthority.BOUNDED,
            result=public,
            bounds=_normalize_bounds(request.get("bounds")),
            request_id=request_id,
            cache=_empty_cache(source="proof_candidate_validator"),
        )

    def execute_proof_plan(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Bounded local plan readiness check — never mutates supervisor state.

        Datasets APIs do not expose supervisor-only mutation controls.  This
        operation validates plan structure, cancellation, and resource bounds,
        and returns a readiness report.  Proof success requires independent
        fresh receipts and is never implied by transport success.
        """

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "execute_proof_plan",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={
                    "cancelled": True,
                    "executed": False,
                    "proof_success": False,
                    "supervisor_mutated": False,
                },
                diagnostics=("cancelled before plan execution readiness check",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "execute_proof_plan",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "execute_proof_plan")
        if forbidden:
            return _response(
                "execute_proof_plan",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )

        plan = request.get("plan") or request.get("proof_plan") or request
        if not isinstance(plan, Mapping):
            return _response(
                "execute_proof_plan",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("plan must be a mapping",),
                request_id=request_id,
            )
        plan_id = str(plan.get("plan_id") or request.get("plan_id") or "").strip()
        steps = plan.get("steps") or plan.get("candidates") or ()
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            return _response(
                "execute_proof_plan",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("plan.steps must be a sequence",),
                request_id=request_id,
            )
        if not plan_id:
            plan_id = f"plan:{stable_digest({'steps': list(steps)})[:16]}"

        step_ids: list[str] = []
        missing_fields: list[str] = []
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                missing_fields.append(f"steps[{index}]:not_object")
                continue
            sid = str(step.get("step_id") or step.get("candidate_id") or f"step:{index}")
            step_ids.append(sid)
            if step.get("proof_claimed") is True or step.get("completion_claimed") is True:
                missing_fields.append(f"{sid}:proof_claimed_without_receipt")
            if not (step.get("obligation_id") or step.get("statement")):
                missing_fields.append(f"{sid}:missing_obligation")

        ready = not missing_fields and len(step_ids) > 0
        # Explicit: transport envelope success must not mean proof success.
        result = {
            "plan_id": plan_id,
            "ready": ready,
            "executed": False,
            "supervisor_mutated": False,
            "proof_success": False,
            "step_ids": step_ids,
            "step_count": len(step_ids),
            "blocking_issues": missing_fields,
            "goal_tactician_interface": GOAL_TACTICIAN_API_INTERFACE,
            "mode": "local_readiness",
            "note": (
                "datasets execute_proof_plan performs local readiness only; "
                "supervisor lifecycle ownership remains out of band"
            ),
        }
        status = VerificationStatus.SUCCEEDED if ready else VerificationStatus.PARTIAL
        if not step_ids:
            status = VerificationStatus.INVALID
        return _response(
            "execute_proof_plan",
            status,
            authority=VerificationAuthority.BOUNDED,
            result=result,
            bounds=_normalize_bounds(request.get("bounds") or plan.get("bounds")),
            diagnostics=tuple(missing_fields[:32]),
            request_id=request_id,
            cache=_empty_cache(source="goal_tactician_local_readiness"),
        )

    def proof_status(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Report closed status identities for a plan / goal without mutation."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "proof_status",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True, "proof_success": False},
                diagnostics=("cancelled before proof status",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "proof_status",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "proof_status")
        if forbidden:
            return _response(
                "proof_status",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )

        plan = request.get("plan") if isinstance(request.get("plan"), Mapping) else request
        plan_id = str(plan.get("plan_id") or request.get("plan_id") or "").strip()
        status_text = str(
            plan.get("status")
            or request.get("status")
            or plan.get("plan_status")
            or "unknown"
        ).strip().lower()
        receipts = plan.get("receipts") or request.get("receipts") or ()
        receipt_count = len(receipts) if isinstance(receipts, Sequence) and not isinstance(
            receipts, (str, bytes)
        ) else 0
        steps = plan.get("steps") or plan.get("candidates") or ()
        step_count = (
            len(steps)
            if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes))
            else 0
        )
        # Never treat transport-present status alone as proof success.
        claimed_complete = bool(
            plan.get("complete")
            or plan.get("proof_success")
            or status_text in {"complete", "completed", "proved", "closed"}
        )
        proof_success = claimed_complete and receipt_count > 0 and step_count > 0
        availability = "declared"
        if status_text in {"unavailable", "missing"}:
            availability = "unavailable"
        result = {
            "plan_id": plan_id or f"plan:{stable_digest(dict(plan))[:16]}",
            "status": status_text,
            "availability": availability,
            "step_count": step_count,
            "receipt_count": receipt_count,
            "proof_success": proof_success,
            "transport_ok": True,
            "goal_tactician_interface": GOAL_TACTICIAN_API_INTERFACE,
            "identity": stable_digest(
                {
                    "plan_id": plan_id,
                    "status": status_text,
                    "step_count": step_count,
                    "receipt_count": receipt_count,
                }
            ),
        }
        api_status = VerificationStatus.SUCCEEDED
        if not proof_success and claimed_complete:
            api_status = VerificationStatus.PARTIAL
            result["diagnostics_note"] = (
                "completion claim rejected without adequate receipts"
            )
        elif status_text in {"unknown", ""}:
            api_status = VerificationStatus.PARTIAL
        return _response(
            "proof_status",
            api_status,
            authority=VerificationAuthority.BOUNDED if proof_success else VerificationAuthority.NONE,
            result=result,
            request_id=request_id,
            cache=_empty_cache(source="goal_tactician_status"),
        )

    def minimize_counterexample(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Oracle-preserving semantic counterexample minimization (public-safe)."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "minimize_counterexample",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True},
                diagnostics=("cancelled before minimization",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "minimize_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping with witness",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "minimize_counterexample")
        if forbidden:
            return _response(
                "minimize_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )
        witness = request.get("witness")
        if not isinstance(witness, Mapping):
            return _response(
                "minimize_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("witness object is required",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.software_verification.counterexamples.minimization import (
                MinimizationError,
                minimize_counterexample as _minimize,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "minimize_counterexample",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    f"minimization import failed: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )

        oracle = request.get("oracle")
        if callable(oracle):
            violation_oracle = oracle
        else:
            # Default fail-closed oracle: preserve the original witness as violating.
            seed = _redact_public_mapping(witness)

            def violation_oracle(candidate: Mapping[str, Any]) -> bool:
                # Preserve violation when assignment keys stay a subset of the seed.
                if not isinstance(candidate, Mapping):
                    return False
                seed_assign = seed.get("assignments") or seed.get("model") or seed
                cand_assign = candidate.get("assignments") or candidate.get("model") or candidate
                if not isinstance(seed_assign, Mapping) or not isinstance(cand_assign, Mapping):
                    return candidate == seed
                return all(
                    cand_assign.get(key) == value
                    for key, value in seed_assign.items()
                    if value is not None
                ) or candidate == seed

        try:
            outcome = _minimize(
                dict(witness),
                violation_oracle,
                family=request.get("family"),
                budget=request.get("budget"),
                oracle_id=str(request.get("oracle_id") or "oracle:public"),
                property_snapshot_id=str(request.get("property_snapshot_id") or ""),
                assumption_ids=request.get("assumption_ids"),
                finite_bounds=request.get("finite_bounds") or request.get("bounds"),
            )
        except MinimizationError as exc:
            return _response(
                "minimize_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "minimize_counterexample",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(outcome.to_dict())
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["proof_success"] = False
        return _response(
            "minimize_counterexample",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.BOUNDED,
            result=public,
            witnesses=(public.get("witness") or {},),
            bounds=_normalize_bounds(request.get("finite_bounds") or request.get("bounds")),
            assumptions=tuple(request.get("assumption_ids") or ()),
            request_id=request_id,
            cache=_empty_cache(source="semantic_counterexample_minimizer"),
        )

    def explain_counterexample_causal(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Causal / first-divergence counterexample explanation (public-safe)."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "explain_counterexample_causal",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True},
                diagnostics=("cancelled before causal explanation",),
                request_id=request_id,
            )
        if isinstance(request, Mapping):
            forbidden = _reject_forbidden_controls(request, "explain_counterexample_causal")
            if forbidden:
                return _response(
                    "explain_counterexample_causal",
                    VerificationStatus.INVALID,
                    authority=VerificationAuthority.NONE,
                    diagnostics=(forbidden,),
                    unsupported_features=("supervisor_only_control",),
                    request_id=request_id,
                )
            witness = request.get("witness", request)
            expected = request.get("expected")
            proof_holes = request.get("proof_holes")
            violated_property = str(
                request.get("violated_property") or request.get("property_id") or ""
            )
            assumption_ids = request.get("assumption_ids") or ()
            finite_bounds = request.get("finite_bounds") or request.get("bounds")
            replay_receipt = request.get("replay_receipt")
            replay_verified = request.get("replay_verified")
        else:
            witness = request
            expected = None
            proof_holes = None
            violated_property = ""
            assumption_ids = ()
            finite_bounds = None
            replay_receipt = None
            replay_verified = None
        if witness is None:
            return _response(
                "explain_counterexample_causal",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("witness is required",),
                request_id=request_id,
            )
        try:
            from ipfs_datasets_py.logic.software_verification.counterexamples.explanation import (
                COUNTEREXAMPLE_EXPLANATION_INTERFACE,
                ExplanationError,
                explain_counterexample as _explain_causal,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "explain_counterexample_causal",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(
                    f"explanation import failed: {type(error).__name__}: {error}",
                ),
                request_id=request_id,
            )
        try:
            explanation = _explain_causal(
                witness,
                expected=expected,
                proof_holes=proof_holes,
                replay_receipt=replay_receipt,
                replay_verified=replay_verified,
                violated_property=violated_property,
                assumption_ids=assumption_ids,
                finite_bounds=finite_bounds,
            )
        except ExplanationError as exc:
            return _response(
                "explain_counterexample_causal",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "explain_counterexample_causal",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(explanation.to_dict())
        public["explanation_interface"] = COUNTEREXAMPLE_EXPLANATION_INTERFACE
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["proof_success"] = False
        return _response(
            "explain_counterexample_causal",
            VerificationStatus.SUCCEEDED,
            authority=VerificationAuthority.BOUNDED,
            result=public,
            assumptions=tuple(assumption_ids or ()),
            bounds=_normalize_bounds(finite_bounds),
            request_id=request_id,
            property_id=violated_property,
            cache=_empty_cache(source="counterexample_explanation"),
        )

    def replay_counterexample(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_id: str = "",
        cancellation: object | None = None,
    ) -> VerificationResponse:
        """Exact-binding counterexample replay through the public-safe recipe path."""

        request_id = _text(request_id, "request_id", optional=True)
        if _is_cancelled(cancellation):
            return _response(
                "replay_counterexample",
                VerificationStatus.PARTIAL,
                authority=VerificationAuthority.NONE,
                result={"cancelled": True, "reproduced": False},
                diagnostics=("cancelled before replay",),
                request_id=request_id,
            )
        if not isinstance(request, Mapping):
            return _response(
                "replay_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=("request must be a mapping",),
                request_id=request_id,
            )
        forbidden = _reject_forbidden_controls(request, "replay_counterexample")
        if forbidden:
            return _response(
                "replay_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(forbidden,),
                unsupported_features=("supervisor_only_control",),
                request_id=request_id,
            )
        recipe = request.get("recipe", request.get("witness", request))
        try:
            from ipfs_datasets_py.logic.software_verification.counterexamples.replay import (
                COUNTEREXAMPLE_REPLAY_INTERFACE,
                ReplayError,
                ReplayStatus,
                replay_counterexample as _replay,
            )
        except Exception as error:  # pragma: no cover
            return _response(
                "replay_counterexample",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"replay import failed: {type(error).__name__}: {error}",),
                request_id=request_id,
            )
        oracle = request.get("oracle")
        if not callable(oracle):
            # Default oracle: treat presence of a public payload as still violating.
            def oracle(candidate: Mapping[str, Any]) -> bool:  # type: ignore[misc]
                return isinstance(candidate, Mapping)

        try:
            outcome = _replay(
                recipe,
                oracle=oracle,
                observed_bindings=request.get("observed_bindings"),
                tool_available=request.get("tool_available", True),
                oracle_id=str(request.get("oracle_id") or "oracle:public"),
            )
        except ReplayError as exc:
            return _response(
                "replay_counterexample",
                VerificationStatus.INVALID,
                authority=VerificationAuthority.NONE,
                diagnostics=(str(exc),),
                request_id=request_id,
            )
        except Exception as error:
            return _response(
                "replay_counterexample",
                VerificationStatus.ERROR,
                authority=VerificationAuthority.NONE,
                diagnostics=(f"{type(error).__name__}: {error}",),
                request_id=request_id,
            )

        public = _redact_public_mapping(outcome.to_dict())
        public["replay_interface"] = COUNTEREXAMPLE_REPLAY_INTERFACE
        public["goal_tactician_interface"] = GOAL_TACTICIAN_API_INTERFACE
        public["proof_success"] = False
        status_value = public.get("status")
        if status_value == getattr(ReplayStatus, "REPRODUCED", "reproduced") or status_value == "reproduced":
            api_status = VerificationStatus.SUCCEEDED
        elif status_value in {"unavailable", ReplayStatus.UNAVAILABLE if hasattr(ReplayStatus, "UNAVAILABLE") else "unavailable"}:
            api_status = VerificationStatus.UNAVAILABLE
        elif status_value in {
            "binding_mismatch",
            getattr(ReplayStatus, "BINDING_MISMATCH", "binding_mismatch"),
        }:
            api_status = VerificationStatus.PARTIAL
        else:
            api_status = VerificationStatus.PARTIAL
        return _response(
            "replay_counterexample",
            api_status,
            authority=VerificationAuthority.BOUNDED,
            result=public,
            request_id=request_id,
            cache=_empty_cache(source="counterexample_replay"),
        )

    def invoke_goal_tactician(
        self,
        operation: str,
        request: Mapping[str, Any] | None = None,
        *,
        request_id: str = "",
        cancellation: object | None = None,
        **kwargs: Any,
    ) -> VerificationResponse:
        """Channel-neutral dispatcher for GoalTacticianAPI@1 operations."""

        operation = _text(operation, "operation")
        if operation not in GOAL_TACTICIAN_OPERATIONS:
            return _response(
                operation,
                VerificationStatus.UNSUPPORTED,
                authority=VerificationAuthority.NONE,
                unsupported_features=(f"goal_tactician:{operation}",),
                diagnostics=(f"unknown goal tactician operation: {operation}",),
                request_id=request_id,
            )
        payload = dict(request or {})
        payload.update({key: value for key, value in kwargs.items() if value is not None})
        if operation == "list_goal_tactician_operations":
            return self.list_goal_tactician_operations(request_id=request_id)
        if operation == "formalize_goal":
            return self.formalize_goal(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "compare_interpretations":
            return self.compare_interpretations(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "discover_missing_proofs":
            surface = payload.get("surface", payload.get("request", payload))
            return self.discover_missing_proofs(
                surface,
                request_id=request_id,
                require_source_spans=bool(payload.get("require_source_spans", True)),
                cancellation=cancellation,
            )
        if operation == "plan_proof":
            return self.plan_proof(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "validate_proof_candidate":
            return self.validate_proof_candidate(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "execute_proof_plan":
            return self.execute_proof_plan(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "proof_status":
            return self.proof_status(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "minimize_counterexample":
            return self.minimize_counterexample(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "explain_counterexample_causal":
            return self.explain_counterexample_causal(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        if operation == "replay_counterexample":
            return self.replay_counterexample(
                payload.get("request", payload),
                request_id=request_id,
                cancellation=cancellation,
            )
        return _response(
            operation,
            VerificationStatus.UNSUPPORTED,
            authority=VerificationAuthority.NONE,
            unsupported_features=(f"goal_tactician:{operation}",),
            request_id=request_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "operations": list(STABLE_OPERATIONS),
            "goal_tactician_interface": GOAL_TACTICIAN_API_INTERFACE,
            "goal_tactician_operations": list(GOAL_TACTICIAN_OPERATIONS),
            "version": self.version,
        }


_DEFAULT_API: LogicVerificationAPI | None = None


def get_verification_api(
    *,
    backend_registry: Any | None = None,
    reset: bool = False,
) -> LogicVerificationAPI:
    """Return the process-local default verification API facade."""

    global _DEFAULT_API
    if backend_registry is not None:
        return LogicVerificationAPI(backend_registry=backend_registry)
    if reset or _DEFAULT_API is None:
        _DEFAULT_API = LogicVerificationAPI()
    return _DEFAULT_API


# Module-level convenience wrappers (thin, for stable import paths).

def list_logic_families() -> VerificationResponse:
    return get_verification_api().list_logic_families()


def list_providers() -> VerificationResponse:
    return get_verification_api().list_providers()


def provider_capabilities(provider_id: str | None = None) -> VerificationResponse:
    return get_verification_api().provider_capabilities(provider_id)


def compile_verification_artifact(
    artifact: Mapping[str, Any] | Any,
    **kwargs: Any,
) -> VerificationResponse:
    return get_verification_api().compile_verification_artifact(artifact, **kwargs)


def check(request: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().check(request, **kwargs)


def monitor(
    formula: Any,
    observations: Sequence[Any] | Mapping[str, Any],
    **kwargs: Any,
) -> VerificationResponse:
    return get_verification_api().monitor(formula, observations, **kwargs)


def run_portfolio(obligation: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().run_portfolio(obligation, **kwargs)


def explain_counterexample(witness: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().explain_counterexample(witness, **kwargs)


def verify_receipt(receipt: Any, expectation: Any | None = None, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().verify_receipt(receipt, expectation, **kwargs)


def attest_receipt(receipt: Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().attest_receipt(receipt, **kwargs)


def advise(request: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().advise(request, **kwargs)


def probe_provider(provider_id: str, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().probe_provider(provider_id, **kwargs)


def install_provider(provider_id: str, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().install_provider(provider_id, **kwargs)


def list_goal_tactician_operations(**kwargs: Any) -> VerificationResponse:
    return get_verification_api().list_goal_tactician_operations(**kwargs)


def formalize_goal(request: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().formalize_goal(request, **kwargs)


def compare_interpretations(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().compare_interpretations(request, **kwargs)


def discover_missing_proofs(
    surface: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().discover_missing_proofs(surface, **kwargs)


def plan_proof(request: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().plan_proof(request, **kwargs)


def validate_proof_candidate(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().validate_proof_candidate(request, **kwargs)


def execute_proof_plan(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().execute_proof_plan(request, **kwargs)


def proof_status(request: Mapping[str, Any] | Any, **kwargs: Any) -> VerificationResponse:
    return get_verification_api().proof_status(request, **kwargs)


def minimize_counterexample(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().minimize_counterexample(request, **kwargs)


def explain_counterexample_causal(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().explain_counterexample_causal(request, **kwargs)


def replay_counterexample(
    request: Mapping[str, Any] | Any, **kwargs: Any
) -> VerificationResponse:
    return get_verification_api().replay_counterexample(request, **kwargs)


def invoke_goal_tactician(
    operation: str,
    request: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> VerificationResponse:
    return get_verification_api().invoke_goal_tactician(operation, request, **kwargs)


def invoke_goal_tactician_mcp_tool(
    tool_name: str,
    request: Mapping[str, Any] | None = None,
    *,
    request_id: str = "",
    cancellation: object | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Datasets/parent MCP adapter for GoalTacticianCLIMCP@1 tools.

    Returns the shared logic-verification response envelope as a dict.  Transport
    success is independent of proof success (see ``result.proof_success``).
    """

    operation = GOAL_TACTICIAN_TOOL_TO_OPERATION.get(tool_name)
    if operation is None:
        payload = _response(
            tool_name,
            VerificationStatus.UNSUPPORTED,
            authority=VerificationAuthority.NONE,
            unsupported_features=(f"mcp_tool:{tool_name}",),
            diagnostics=(f"unknown goal tactician MCP tool: {tool_name}",),
            request_id=request_id,
        ).to_dict()
        payload["success"] = False
        payload["channel"] = "mcp"
        payload["tool"] = tool_name
        payload["mcp_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
        return payload
    response = get_verification_api().invoke_goal_tactician(
        operation,
        request,
        request_id=request_id,
        cancellation=cancellation,
        **kwargs,
    )
    payload = response.to_dict()
    payload["success"] = response.status not in {
        VerificationStatus.ERROR,
        VerificationStatus.INVALID,
        VerificationStatus.UNSUPPORTED,
    }
    payload["channel"] = "mcp"
    payload["tool"] = tool_name
    payload["mcp_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
    payload["cli_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
    payload["python_operation"] = operation
    return payload


def invoke_goal_tactician_cli(
    command: str,
    request: Mapping[str, Any] | None = None,
    *,
    request_id: str = "",
    cancellation: object | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """CLI adapter for GoalTacticianCLIMCP@1 commands (schema-equivalent to MCP)."""

    operation = GOAL_TACTICIAN_CLI_TO_OPERATION.get(command)
    if operation is None:
        payload = _response(
            command,
            VerificationStatus.UNSUPPORTED,
            authority=VerificationAuthority.NONE,
            unsupported_features=(f"cli_command:{command}",),
            diagnostics=(f"unknown goal tactician CLI command: {command}",),
            request_id=request_id,
        ).to_dict()
        payload["success"] = False
        payload["channel"] = "cli"
        payload["command"] = command
        payload["cli_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
        return payload
    response = get_verification_api().invoke_goal_tactician(
        operation,
        request,
        request_id=request_id,
        cancellation=cancellation,
        **kwargs,
    )
    payload = response.to_dict()
    payload["success"] = response.status not in {
        VerificationStatus.ERROR,
        VerificationStatus.INVALID,
        VerificationStatus.UNSUPPORTED,
    }
    payload["channel"] = "cli"
    payload["command"] = command
    payload["cli_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
    payload["mcp_interface"] = GOAL_TACTICIAN_CLI_MCP_INTERFACE
    payload["python_operation"] = operation
    return payload


__all__ = [
    "ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE",
    "CLOSED_RECEIPT_SCHEMAS",
    "CacheProvenance",
    "EXECUTABLE_PROVIDER_MATRIX_INTERFACE",
    "FORMAL_VERIFICATION_MCP_PARITY_INTERFACE",
    "FeatureAvailability",
    "FeatureDescriptor",
    "GOAL_TACTICIAN_API_INTERFACE",
    "GOAL_TACTICIAN_API_VERSION",
    "GOAL_TACTICIAN_CLI_COMMANDS",
    "GOAL_TACTICIAN_CLI_MCP_INTERFACE",
    "GOAL_TACTICIAN_CLI_TO_OPERATION",
    "GOAL_TACTICIAN_OPERATIONS",
    "GOAL_TACTICIAN_REQUEST_SCHEMA",
    "GOAL_TACTICIAN_RESPONSE_SCHEMA",
    "GOAL_TACTICIAN_TOOL_NAMES",
    "GOAL_TACTICIAN_TOOL_TO_OPERATION",
    "LOGIC_TRANSLATION_RECEIPT_SCHEMA",
    "LOGIC_VERIFICATION_API_INTERFACE",
    "LOGIC_VERIFICATION_API_VERSION",
    "LogicVerificationAPI",
    "ProviderDescriptor",
    "STABLE_OPERATIONS",
    "TRUSTED_PROOF_RECEIPT_SCHEMA",
    "VERIFIED_RECEIPT_DISPATCH_INTERFACE",
    "VerificationAPIError",
    "VerificationAuthority",
    "VerificationResponse",
    "VerificationStatus",
    "advise",
    "attest_receipt",
    "check",
    "compare_interpretations",
    "compile_verification_artifact",
    "discover_missing_proofs",
    "execute_proof_plan",
    "explain_counterexample",
    "explain_counterexample_causal",
    "formalize_goal",
    "get_verification_api",
    "goal_tactician_tool_schemas",
    "install_provider",
    "invoke_goal_tactician",
    "invoke_goal_tactician_cli",
    "invoke_goal_tactician_mcp_tool",
    "list_goal_tactician_cli_mcp_surface",
    "list_goal_tactician_operations",
    "list_logic_families",
    "list_providers",
    "list_stable_features",
    "minimize_counterexample",
    "monitor",
    "plan_proof",
    "probe_provider",
    "proof_status",
    "provider_capabilities",
    "replay_counterexample",
    "run_portfolio",
    "validate_proof_candidate",
    "verify_receipt",
]
