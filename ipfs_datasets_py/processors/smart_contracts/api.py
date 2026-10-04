"""Read-only smart-contract service API (CRYPTOIR-G600 / CRYPTOIR-034).

:class:`SmartContractProcessorAPI` is the public, non-custodial facade for
artifact acquisition and capability discovery.  CLI/MCP/Python consumers share
the same typed request surface.

Design constraints:

* Acquisition, parse, and analyze capabilities are explicit and separately
  injected — acquisition never implies parse or analyze authority.
* No signing, broadcast, private-key, seed, or submit verbs exist on this
  surface; attempts raise :class:`SigningForbiddenError`.
* No ``approved=true`` compatibility escape hatch.
* Importing this module performs no network I/O and does not load chain extras.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Final

from .errors import (
    InvalidRequestError,
    SigningForbiddenError,
    SmartContractProcessorError,
    UnsupportedCapabilityError,
)
from .models import (
    ContractAcquisitionRequest,
    ContractAcquisitionResult,
    assert_no_signing_surface,
)
from .protocols import (
    ACQUISITION_CAPABILITIES,
    ANALYZE_CAPABILITIES,
    PARSE_CAPABILITIES,
    ArtifactProvider,
    Capabilities,
    Capability,
    ContractAnalyzer,
    ContractParser,
    SmartContractProcessor,
    reject_signing_surface,
)


API_SCHEMA_VERSION: Final = "smart-contract-api-v1"
_FORBIDDEN_VERBS: Final[frozenset[str]] = frozenset(
    {
        "sign",
        "broadcast",
        "submit",
        "approve_payload",
        "sign_transaction",
        "broadcast_transaction",
        "send",
        "transfer",
        "send_raw_transaction",
        "approve",
    }
)
_FORBIDDEN_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approve",
        "private_key",
        "privateKey",
        "seed",
        "mnemonic",
        "signing_key",
        "force_allow",
        "skip_guard",
        "bypass_guard",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class SmartContractCapabilitiesResult:
    """Inspectable read-only capability catalogue."""

    providers: tuple[dict[str, Any], ...]
    supports_sign: bool = False
    supports_broadcast: bool = False
    schema_version: str = API_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": list(self.providers),
            "schema_version": self.schema_version,
            "supports_broadcast": False,
            "supports_sign": False,
        }


@dataclass(frozen=True, slots=True)
class SmartContractAcquireResult:
    """Sanitized acquisition receipt for API consumers."""

    status: str
    request_id: str | None
    artifact_count: int
    warnings: tuple[str, ...] = ()
    result: ContractAcquisitionResult | None = None
    schema_version: str = API_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_count": self.artifact_count,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "warnings": list(self.warnings),
        }
        if self.result is not None:
            raw = self.result.to_dict() if hasattr(self.result, "to_dict") else {}
            assert_no_signing_surface(raw)
            payload["result"] = raw
        return payload


class SmartContractProcessorAPI:
    """Read-only smart-contract acquisition and capability facade.

    Parameters
    ----------
    provider:
        Optional injected :class:`ArtifactProvider` (tests / hosts inject
        offline fixtures; production hosts inject egress-bounded providers).
    parser / analyzer:
        Optional parse/analyze capabilities; never implied by acquisition.
    processor:
        Optional composite :class:`SmartContractProcessor`.
    """

    FORBIDDEN_OPERATIONS = _FORBIDDEN_VERBS

    def __init__(
        self,
        *,
        provider: ArtifactProvider | None = None,
        parser: ContractParser | None = None,
        analyzer: ContractAnalyzer | None = None,
        processor: SmartContractProcessor | None = None,
        clock: Any | None = None,
    ) -> None:
        self._provider = provider
        self._parser = parser
        self._analyzer = analyzer
        self._processor = processor
        self._clock = clock or _utc_now

    # -- discovery ----------------------------------------------------------

    def list_capabilities(self) -> SmartContractCapabilitiesResult:
        """Return declared capabilities without performing acquisition."""

        providers: list[dict[str, Any]] = []
        if self._provider is not None:
            caps = getattr(self._provider, "capabilities", None)
            if callable(caps):
                declared = caps()
            else:
                declared = caps
            entry = self._capabilities_entry("artifact_provider", declared)
            providers.append(entry)
        if self._parser is not None:
            providers.append(
                {
                    "role": "parser",
                    "features": sorted(c.value for c in PARSE_CAPABILITIES),
                    "supports_sign": False,
                    "supports_broadcast": False,
                }
            )
        if self._analyzer is not None:
            providers.append(
                {
                    "role": "analyzer",
                    "features": sorted(c.value for c in ANALYZE_CAPABILITIES),
                    "supports_sign": False,
                    "supports_broadcast": False,
                }
            )
        if self._processor is not None:
            providers.append(
                {
                    "role": "processor",
                    "features": sorted(c.value for c in ACQUISITION_CAPABILITIES),
                    "supports_sign": False,
                    "supports_broadcast": False,
                }
            )
        return SmartContractCapabilitiesResult(providers=tuple(providers))

    def capabilities(self) -> SmartContractCapabilitiesResult:
        return self.list_capabilities()

    # -- acquisition --------------------------------------------------------

    def acquire(
        self,
        request: ContractAcquisitionRequest | Mapping[str, Any],
        *,
        options: Mapping[str, Any] | None = None,
    ) -> SmartContractAcquireResult:
        """Acquire artifacts through the injected provider only.

        Raises :class:`UnsupportedCapabilityError` when no provider is
        configured.  Never signs or broadcasts.
        """

        self._assert_not_forbidden_options(options or {})
        if isinstance(request, Mapping):
            self._assert_not_forbidden_options(request)
            if hasattr(ContractAcquisitionRequest, "from_dict"):
                request = ContractAcquisitionRequest.from_dict(request)
            else:
                raise InvalidRequestError(
                    "request must be a ContractAcquisitionRequest"
                )
        if not isinstance(request, ContractAcquisitionRequest):
            raise InvalidRequestError(
                "request must be a ContractAcquisitionRequest"
            )
        assert_no_signing_surface(
            request.to_dict() if hasattr(request, "to_dict") else request
        )

        provider = self._provider
        if provider is None and self._processor is not None:
            provider = getattr(self._processor, "provider", None) or getattr(
                self._processor, "artifact_provider", None
            )
        if provider is None:
            raise UnsupportedCapabilityError(
                "no ArtifactProvider is configured; acquisition is explicit "
                "and separately injected"
            )

        acquire_fn = getattr(provider, "acquire", None) or getattr(
            provider, "acquire_artifact", None
        )
        if not callable(acquire_fn):
            raise UnsupportedCapabilityError(
                "configured provider does not expose an acquire method"
            )

        result = acquire_fn(request)
        if not isinstance(result, ContractAcquisitionResult):
            # Allow duck-typed offline fixtures that expose status + to_dict.
            status = str(getattr(result, "status", "error"))
            request_id = getattr(result, "request_id", None)
            artifacts = getattr(result, "artifacts", ()) or ()
            return SmartContractAcquireResult(
                status=status,
                request_id=str(request_id) if request_id is not None else None,
                artifact_count=len(tuple(artifacts)),
                result=None,
                warnings=("non-typed acquisition result",),
            )

        artifacts = getattr(result, "artifacts", ()) or ()
        status_obj = getattr(result, "status", None)
        status = (
            status_obj.value
            if hasattr(status_obj, "value")
            else str(status_obj or "error")
        )
        request_id = getattr(result, "request_id", None) or getattr(
            request, "request_id", None
        )
        assert_no_signing_surface(result.to_dict())
        return SmartContractAcquireResult(
            status=status,
            request_id=str(request_id) if request_id is not None else None,
            artifact_count=len(tuple(artifacts)),
            result=result,
        )

    # -- forbidden custody surface ------------------------------------------

    def _assert_not_forbidden_options(self, options: Mapping[str, Any]) -> None:
        for key in options:
            lowered = str(key).strip().lower()
            if (
                lowered in _FORBIDDEN_VERBS
                or lowered in _FORBIDDEN_OPTIONS
                or lowered.startswith("sign_")
            ):
                raise SigningForbiddenError(
                    f"operation option {key!r} is forbidden on the read-only "
                    "smart-contract API; no approved=true escape hatch exists"
                )

    def __getattr__(self, name: str) -> Any:
        if name in self.FORBIDDEN_OPERATIONS or name.startswith("sign_"):
            reject_signing_surface(name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    @staticmethod
    def _capabilities_entry(
        role: str, declared: Capabilities | Mapping[str, Any] | None
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "role": role,
            "supports_sign": False,
            "supports_broadcast": False,
        }
        if isinstance(declared, Capabilities):
            entry.update(
                {
                    "provider": declared.provider,
                    "chain_namespaces": sorted(declared.chain_namespaces),
                    "features": sorted(f.value for f in declared.features),
                    "metadata": dict(declared.metadata),
                }
            )
        elif isinstance(declared, Mapping):
            entry.update(dict(declared))
            entry["supports_sign"] = False
            entry["supports_broadcast"] = False
        return entry


_DEFAULT_API: SmartContractProcessorAPI | None = None


def get_default_smart_contract_api() -> SmartContractProcessorAPI:
    global _DEFAULT_API
    if _DEFAULT_API is None:
        _DEFAULT_API = SmartContractProcessorAPI()
    return _DEFAULT_API


def reset_default_smart_contract_api() -> None:
    global _DEFAULT_API
    _DEFAULT_API = None


__all__ = [
    "API_SCHEMA_VERSION",
    "SmartContractAcquireResult",
    "SmartContractCapabilitiesResult",
    "SmartContractProcessorAPI",
    "get_default_smart_contract_api",
    "reset_default_smart_contract_api",
]
