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
    return tuple(features)


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
            result={"providers": providers, "count": len(providers)},
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
    ) -> VerificationResponse:
        """Plan a property-specific prover portfolio (pure planning)."""

        request_id = _text(request_id, "request_id", optional=True)
        try:
            from ipfs_datasets_py.logic.backends.portfolio import (
                PortfolioCapability,
                PortfolioObligation,
                PortfolioResourcePolicy,
                plan_portfolio,
            )
            from ipfs_datasets_py.logic.software_verification.properties import PropertyKind
            from ipfs_datasets_py.logic.families.models import EvidenceAuthority
        except Exception as error:
            return _response(
                "run_portfolio",
                VerificationStatus.UNAVAILABLE,
                authority=VerificationAuthority.NONE,
                unsupported_features=("verification_portfolio",),
                diagnostics=(f"portfolio module unavailable: {type(error).__name__}: {error}",),
                request_id=request_id,
            )

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

            caps: list[Any] = []
            if capabilities is None:
                # Derive declared portfolio capabilities from the backend registry.
                registry = self._registry()
                for backend_id, backend_caps in registry.capabilities.items():
                    from ipfs_datasets_py.logic.backends.portfolio import (
                        AttemptFamily,
                        CapabilityStatus,
                    )

                    families = set(getattr(backend_caps, "logic_families", ()) or ())
                    family = AttemptFamily.SOLVER
                    if "hyperproperty" in families:
                        family = AttemptFamily.HYPERPROPERTY
                    caps.append(
                        PortfolioCapability(
                            backend_id=backend_id,
                            family=family,
                            status=CapabilityStatus.DECLARED,
                        )
                    )
            elif isinstance(capabilities, Mapping):
                caps = list(capabilities.values())
            else:
                caps = list(capabilities)

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
        return _response(
            "run_portfolio",
            VerificationStatus.SUCCEEDED if not gaps else VerificationStatus.PARTIAL,
            authority=VerificationAuthority.BOUNDED,
            result={
                "plan": plan_dict,
                "capability_gaps": gaps,
                "attempt_count": len(getattr(plan, "attempts", ()) or ()),
            },
            assumptions=tuple(portfolio_obligation.assumption_ids),
            bounds=policy.to_dict() if hasattr(policy, "to_dict") else {},
            unsupported_features=unsupported,
            request_id=request_id or portfolio_obligation.obligation_id,
            property_id=portfolio_obligation.obligation_id,
            cache=_empty_cache(source="portfolio_plan"),
        )

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "operations": list(STABLE_OPERATIONS),
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


__all__ = [
    "ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE",
    "CLOSED_RECEIPT_SCHEMAS",
    "CacheProvenance",
    "FeatureAvailability",
    "FeatureDescriptor",
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
    "compile_verification_artifact",
    "explain_counterexample",
    "get_verification_api",
    "install_provider",
    "list_logic_families",
    "list_providers",
    "list_stable_features",
    "monitor",
    "probe_provider",
    "provider_capabilities",
    "run_portfolio",
    "verify_receipt",
]
