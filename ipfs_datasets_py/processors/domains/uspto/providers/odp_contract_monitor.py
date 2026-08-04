"""Opt-in ODP authentication / profile contract canary (PATLAW-124).

Probes the announced 2026 USPTO.gov sign-in and profile requirements without
exposing API keys. Distinguishes:

* 401 authentication failures
* 403 profile / authorization drift
* 429 quota / rate limits
* 5xx upstream outages
* empty / not-found application results
* successful bounded probes

Live network I/O is **opt-in** via explicit canary configuration. Tests inject
recorded or fake transports. Importing this module performs no network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    DEFAULT_ODP_BASE_URL,
    ProviderOutcomeKind,
    ProviderResult,
    sanitize_secret_text,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PROVIDER_NAME,
    PatentFileWrapperClient,
)

ODP_CONTRACT_MONITOR_SCHEMA_VERSION: Final = "uspto.odp.contract-monitor.v1"
ODP_CONTRACT_MONITOR_INTERFACE: Final = "OdpContractMonitor@1"

# Announced ODP authentication contract milestones (diagnostic labels only).
SIGN_IN_REQUIREMENT_EFFECTIVE: Final = "2026-06-18"
PROFILE_REQUIREMENT_EFFECTIVE: Final = "2026-08-18"

# Default probe path: meta-data for a well-known synthetic/public number.
# Operators override via configuration; empty results are first-class outcomes.
DEFAULT_CANARY_APPLICATION_NUMBER: Final = "16123456"


class ContractCanaryKind(str, Enum):
    """Operator-distinguishable canary outcome classes."""

    AUTHENTICATION_FAILURE = "authentication_failure"  # 401
    PROFILE_OR_AUTHORIZATION_DRIFT = "profile_or_authorization_drift"  # 403
    QUOTA_OR_RATE_LIMIT = "quota_or_rate_limit"  # 429
    UPSTREAM_OUTAGE = "upstream_outage"  # 5xx / transport
    EMPTY_OR_NOT_FOUND = "empty_or_not_found"  # 404 / empty bag
    SUCCESS = "success"
    CLIENT_ERROR = "client_error"
    SCHEMA_OR_MALFORMED = "schema_or_malformed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContractCanaryResult:
    """Redacted canary observation — never carries secret material."""

    schema_version: str
    kind: ContractCanaryKind
    provider_kind: str
    status_code: int | None
    message: str
    application_number: str | None
    endpoint_fingerprint: str | None
    sign_in_requirement_effective: str
    profile_requirement_effective: str
    opt_in: bool
    metadata: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "kind": self.kind.value,
            "message": self.message,
            "metadata": dict(self.metadata),
            "opt_in": self.opt_in,
            "profile_requirement_effective": self.profile_requirement_effective,
            "provider_kind": self.provider_kind,
            "schema_version": self.schema_version,
            "sign_in_requirement_effective": self.sign_in_requirement_effective,
            "status_code": self.status_code,
        }

    @property
    def is_auth_drift(self) -> bool:
        return self.kind in {
            ContractCanaryKind.AUTHENTICATION_FAILURE,
            ContractCanaryKind.PROFILE_OR_AUTHORIZATION_DRIFT,
        }

    @property
    def is_quota_or_outage(self) -> bool:
        return self.kind in {
            ContractCanaryKind.QUOTA_OR_RATE_LIMIT,
            ContractCanaryKind.UPSTREAM_OUTAGE,
        }

    @property
    def is_empty_result(self) -> bool:
        return self.kind is ContractCanaryKind.EMPTY_OR_NOT_FOUND


def classify_provider_result(
    result: ProviderResult,
    *,
    application_number: str | None = None,
    opt_in: bool = True,
) -> ContractCanaryResult:
    """Map a typed provider result to a canary kind without leaking secrets."""

    kind = result.kind
    status = result.status_code
    message = sanitize_secret_text(result.message or kind.value)
    meta: dict[str, str] = {
        str(k): sanitize_secret_text(str(v)) for k, v in dict(result.metadata or {}).items()
    }
    fingerprint = None
    if result.receipt is not None:
        endpoint = getattr(result.receipt, "endpoint", None)
        if endpoint:
            # Fingerprint only — full URL may still be public ODP path.
            fingerprint = sanitize_secret_text(str(endpoint))[:256]
        rid = getattr(result.receipt, "response_digest", None)
        if rid:
            meta.setdefault("response_digest_prefix", str(rid)[:16])

    if kind is ProviderOutcomeKind.UNAUTHORIZED or status == 401:
        canary = ContractCanaryKind.AUTHENTICATION_FAILURE
        message = message or "authentication failed (401); API key or USPTO.gov sign-in required"
    elif kind is ProviderOutcomeKind.FORBIDDEN or status == 403:
        canary = ContractCanaryKind.PROFILE_OR_AUTHORIZATION_DRIFT
        message = (
            message
            or "forbidden (403); profile/authorization drift relative to "
            f"ODP contract effective {PROFILE_REQUIREMENT_EFFECTIVE}"
        )
    elif kind is ProviderOutcomeKind.RATE_LIMITED or status == 429:
        canary = ContractCanaryKind.QUOTA_OR_RATE_LIMIT
        message = message or "rate limited / quota exhausted (429)"
    elif kind is ProviderOutcomeKind.NOT_FOUND or status == 404:
        canary = ContractCanaryKind.EMPTY_OR_NOT_FOUND
        message = message or "application not found or empty public result"
    elif kind in {
        ProviderOutcomeKind.UPSTREAM_ERROR,
        ProviderOutcomeKind.TRANSPORT_ERROR,
        ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED,
        ProviderOutcomeKind.CIRCUIT_OPEN,
    } or (isinstance(status, int) and 500 <= status <= 599):
        canary = ContractCanaryKind.UPSTREAM_OUTAGE
        message = message or "upstream outage or transport failure"
    elif kind is ProviderOutcomeKind.CANCELLED:
        canary = ContractCanaryKind.CANCELLED
    elif kind in {
        ProviderOutcomeKind.MALFORMED,
        ProviderOutcomeKind.SCHEMA_DRIFT,
    }:
        canary = ContractCanaryKind.SCHEMA_OR_MALFORMED
    elif kind is ProviderOutcomeKind.CLIENT_ERROR:
        canary = ContractCanaryKind.CLIENT_ERROR
    elif kind in {ProviderOutcomeKind.SUCCESS, ProviderOutcomeKind.NOT_MODIFIED}:
        # Empty bag on 200 is still an empty result for canary purposes.
        payload = result.payload
        empty = False
        if payload is None:
            empty = True
        elif hasattr(payload, "application_meta_data"):
            meta_data = getattr(payload, "application_meta_data", None)
            if not meta_data:
                empty = True
        if empty:
            canary = ContractCanaryKind.EMPTY_OR_NOT_FOUND
            message = "successful HTTP response with empty application payload"
        else:
            canary = ContractCanaryKind.SUCCESS
            message = message or "canary probe succeeded"
    else:
        canary = ContractCanaryKind.UNKNOWN

    return ContractCanaryResult(
        schema_version=ODP_CONTRACT_MONITOR_SCHEMA_VERSION,
        kind=canary,
        provider_kind=kind.value if hasattr(kind, "value") else str(kind),
        status_code=status,
        message=message,
        application_number=application_number,
        endpoint_fingerprint=fingerprint,
        sign_in_requirement_effective=SIGN_IN_REQUIREMENT_EFFECTIVE,
        profile_requirement_effective=PROFILE_REQUIREMENT_EFFECTIVE,
        opt_in=opt_in,
        metadata=MappingProxyType(meta),
    )


@dataclass
class OdpContractMonitor:
    """Bounded, opt-in authentication/profile contract canary.

    Construction is free of network I/O. :meth:`probe` performs a single
    read-only meta-data (or application) fetch only when ``enabled`` is true.
    """

    client: PatentFileWrapperClient
    enabled: bool = False
    application_number: str = DEFAULT_CANARY_APPLICATION_NUMBER
    prefer_meta_data: bool = True

    def safe_config(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "enabled": self.enabled,
            "interface": ODP_CONTRACT_MONITOR_INTERFACE,
            "prefer_meta_data": self.prefer_meta_data,
            "profile_requirement_effective": PROFILE_REQUIREMENT_EFFECTIVE,
            "provider": PROVIDER_NAME,
            "schema_version": ODP_CONTRACT_MONITOR_SCHEMA_VERSION,
            "sign_in_requirement_effective": SIGN_IN_REQUIREMENT_EFFECTIVE,
        }

    def probe(self) -> ContractCanaryResult:
        """Run one canary probe when enabled; otherwise return a disabled stub."""

        if not self.enabled:
            return ContractCanaryResult(
                schema_version=ODP_CONTRACT_MONITOR_SCHEMA_VERSION,
                kind=ContractCanaryKind.UNKNOWN,
                provider_kind="disabled",
                status_code=None,
                message="contract canary disabled (opt-in required)",
                application_number=self.application_number,
                endpoint_fingerprint=None,
                sign_in_requirement_effective=SIGN_IN_REQUIREMENT_EFFECTIVE,
                profile_requirement_effective=PROFILE_REQUIREMENT_EFFECTIVE,
                opt_in=False,
                metadata=MappingProxyType({"enabled": "false"}),
            )

        app_no = str(self.application_number or DEFAULT_CANARY_APPLICATION_NUMBER).strip()
        if self.prefer_meta_data:
            result = self.client.get_meta_data(app_no)
        else:
            result = self.client.get_application_data(app_no)
        return classify_provider_result(
            result, application_number=app_no, opt_in=True
        )


def canary_distinguishes_auth_from_quota(
    auth_result: ContractCanaryResult,
    quota_result: ContractCanaryResult,
) -> bool:
    """True when auth drift and quota/outage classes are disjoint."""

    return auth_result.is_auth_drift and quota_result.is_quota_or_outage and (
        auth_result.kind != quota_result.kind
    )


__all__ = [
    "DEFAULT_CANARY_APPLICATION_NUMBER",
    "DEFAULT_ODP_BASE_URL",
    "ODP_CONTRACT_MONITOR_INTERFACE",
    "ODP_CONTRACT_MONITOR_SCHEMA_VERSION",
    "PROFILE_REQUIREMENT_EFFECTIVE",
    "SIGN_IN_REQUIREMENT_EFFECTIVE",
    "ContractCanaryKind",
    "ContractCanaryResult",
    "OdpContractMonitor",
    "canary_distinguishes_auth_from_quota",
    "classify_provider_result",
]
