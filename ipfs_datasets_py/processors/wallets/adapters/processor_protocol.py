"""Single generic-processor adapter for wallet processors (WALPROC-G600).

Targets the context-aware core protocol only:

* ``ipfs_datasets_py.processors.core.protocol.ProcessorProtocol``
* ``can_handle(ProcessingContext)`` / ``process(ProcessingContext)``

Per the accepted ADR (``docs/architecture/WALLET_PROCESSOR_PROTOCOL_ADR.md``):

* No adapter to the legacy ``can_process(input_source)`` surface.
* No dual registration, fallback, or edits to either generic registry.
* Domain logic stays in chain packages and the wallet registry; this adapter
  only translates bounded generic context into wallet-domain factory calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..errors import InvalidRequestError, WalletProcessorError
from ..protocols import Capability, RequestLimits
from ..registry import (
    AmbiguousNetworkError,
    OptionalDependencyError,
    UnknownProcessorError,
    WalletProcessorRegistry,
    default_registry,
)

ADAPTER_NAME = "WalletProcessorProtocolAdapter"
ADAPTER_VERSION = "1.0.0"
ADAPTER_GENERIC_API = "ipfs_datasets_py.processors.core.protocol.ProcessorProtocol"
LEGACY_CAN_PROCESS_WIRED = False


def _as_mapping(value: object) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    return {}


def _wallet_marker(context: Any) -> dict[str, Any]:
    """Extract wallet-domain routing fields from a ProcessingContext-like object."""

    options = _as_mapping(getattr(context, "options", None))
    metadata = _as_mapping(getattr(context, "metadata", None))
    source = getattr(context, "source", None)

    family = (
        options.get("wallet_family")
        or options.get("family")
        or metadata.get("wallet_family")
        or metadata.get("family")
    )
    network = (
        options.get("network")
        or options.get("wallet_network")
        or metadata.get("network")
        or metadata.get("wallet_network")
    )
    chain_namespace = (
        options.get("chain_namespace")
        or metadata.get("chain_namespace")
        or options.get("namespace")
        or metadata.get("namespace")
    )
    chain_id = (
        options.get("chain_id")
        or metadata.get("chain_id")
        or options.get("wallet_chain_id")
        or metadata.get("wallet_chain_id")
    )
    domain = (
        options.get("domain")
        or metadata.get("domain")
        or options.get("processor_domain")
        or metadata.get("processor_domain")
    )
    operation = (
        options.get("operation")
        or metadata.get("operation")
        or options.get("wallet_operation")
        or "capabilities"
    )

    source_str = str(source).strip() if source is not None and not isinstance(source, (bytes, bytearray)) else ""
    if source_str.lower().startswith("wallet://"):
        # wallet://{family}[/{network}]
        rest = source_str[9:]
        parts = [p for p in rest.split("/") if p]
        if parts and family is None:
            family = parts[0]
        if len(parts) > 1 and network is None:
            network = parts[1]
        domain = domain or "wallet"

    if domain is None and (family is not None or chain_namespace is not None):
        domain = "wallet"

    return {
        "family": family,
        "network": network,
        "chain_namespace": chain_namespace,
        "chain_id": chain_id,
        "domain": domain,
        "operation": str(operation),
        "options": options,
        "metadata": metadata,
    }


class WalletProcessorProtocolAdapter:
    """ADR-selected adapter implementing the core ``ProcessorProtocol`` shape.

    Structural conformance only — we deliberately avoid subclassing the
    Protocol type so import stays light and does not pull optional deps.

    This class intentionally has **no** ``can_process`` method.
    """

    def __init__(
        self,
        registry: WalletProcessorRegistry | None = None,
        *,
        default_family: str | None = None,
        name: str = ADAPTER_NAME,
    ) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._default_family = default_family
        self._name = name

    @property
    def registry(self) -> WalletProcessorRegistry:
        return self._registry

    @property
    def name(self) -> str:
        return self._name

    def get_capabilities(self) -> dict[str, Any]:
        """Core protocol capability discovery (sync)."""

        catalog = {
            family: {
                "extra": self._registry.required_extra(family),
                "features": sorted(
                    f.value for f in self._registry.capabilities_for(family).features
                ),
                "chain_namespaces": sorted(
                    self._registry.capabilities_for(family).chain_namespaces
                ),
                "composes": sorted(self._registry.get_spec(family).composes),
            }
            for family in self._registry.list_families()
        }
        return {
            "name": self._name,
            "version": ADAPTER_VERSION,
            "handles": ["wallet", "ledger", "wallet://"],
            "outputs": ["capabilities", "wallet_records", "metadata"],
            "domain": "wallets",
            "generic_api": ADAPTER_GENERIC_API,
            "legacy_can_process_wired": LEGACY_CAN_PROCESS_WIRED,
            "dual_registration": False,
            "auto_install": False,
            "families": catalog,
            "signing": False,
            "broadcast": False,
        }

    async def can_handle(self, context: Any) -> bool:
        """Return True when *context* is an explicit wallet-domain request."""

        marker = _wallet_marker(context)
        if marker["domain"] not in {None, "wallet", "wallets", "ledger"}:
            return False
        if marker["domain"] is None and marker["family"] is None and marker["chain_namespace"] is None:
            # Require an explicit wallet marker; do not claim all inputs.
            source = getattr(context, "source", None)
            if not (
                isinstance(source, str)
                and source.strip().lower().startswith("wallet://")
            ):
                return False

        try:
            if marker["family"] is not None:
                self._registry.resolve_family(str(marker["family"]))
                return True
            if self._default_family is not None:
                self._registry.resolve_family(self._default_family)
                return True
            if marker["chain_namespace"] is not None or marker["network"] is not None:
                self._registry.resolve_family_for_network(
                    network=marker["network"],
                    chain_namespace=marker["chain_namespace"],
                    chain_id=marker["chain_id"],
                )
                return True
        except (UnknownProcessorError, AmbiguousNetworkError, InvalidRequestError):
            return False
        return False

    async def process(self, context: Any) -> Any:
        """Translate *context* into a wallet-domain factory call and result.

        Imports the core ``ProcessingResult`` lazily so wallets package import
        remains usable without the full processors.core stack in minimal tests.
        """

        from ipfs_datasets_py.processors.core.protocol import ProcessingResult

        marker = _wallet_marker(context)
        started = datetime.now(timezone.utc)
        try:
            family = marker["family"] or self._default_family
            if family is None:
                family = self._registry.resolve_family_for_network(
                    network=marker["network"],
                    chain_namespace=marker["chain_namespace"],
                    chain_id=marker["chain_id"],
                )
            else:
                family = self._registry.resolve_family(str(family))

            options = dict(marker["options"])
            # Strip adapter routing keys before forwarding to the factory.
            for key in (
                "wallet_family",
                "family",
                "network",
                "wallet_network",
                "chain_namespace",
                "namespace",
                "chain_id",
                "wallet_chain_id",
                "domain",
                "processor_domain",
                "operation",
                "wallet_operation",
                "require_capability",
            ):
                options.pop(key, None)

            require_cap = marker["options"].get("require_capability")
            capability = None
            if require_cap is not None:
                capability = (
                    require_cap
                    if isinstance(require_cap, Capability)
                    else Capability(str(require_cap))
                )

            processor = self._registry.get_wallet_processor(
                family,
                network=marker["network"],
                require_capability=capability,
                **options,
            )

            operation = marker["operation"].lower()
            payload = self._run_operation(processor, family, operation, marker, context)

            elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
            return ProcessingResult(
                success=True,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "adapter_version": ADAPTER_VERSION,
                    "generic_api": ADAPTER_GENERIC_API,
                    "legacy_can_process_wired": LEGACY_CAN_PROCESS_WIRED,
                    "family": family,
                    "network": marker["network"],
                    "operation": operation,
                    "elapsed_ms": elapsed_ms,
                    "extra": self._registry.required_extra(family),
                },
                errors=[],
                warnings=[],
                raw_output=payload,
            )
        except (
            UnknownProcessorError,
            AmbiguousNetworkError,
            OptionalDependencyError,
            InvalidRequestError,
            WalletProcessorError,
            ValueError,
            TypeError,
        ) as exc:
            return ProcessingResult(
                success=False,
                metadata={
                    "processor": self._name,
                    "adapter_version": ADAPTER_VERSION,
                    "generic_api": ADAPTER_GENERIC_API,
                    "legacy_can_process_wired": LEGACY_CAN_PROCESS_WIRED,
                    "error_type": type(exc).__name__,
                },
                errors=[str(exc)],
            )

    def _run_operation(
        self,
        processor: Any,
        family: str,
        operation: str,
        marker: Mapping[str, Any],
        context: Any,
    ) -> Mapping[str, Any]:
        """Execute a bounded, non-signing wallet operation for the adapter."""

        if operation in {"capabilities", "status", "describe"}:
            return self._capabilities_payload(processor, family)

        if operation in {"validate_address", "validate"}:
            address = (
                marker["options"].get("address")
                or marker["metadata"].get("address")
                or getattr(context, "source", None)
            )
            if not isinstance(address, str) or not address.strip():
                raise InvalidRequestError("validate_address requires a non-empty address")
            if hasattr(processor, "validate_address"):
                result = processor.validate_address(address.strip())
                return {"family": family, "validation": result}
            raise InvalidRequestError(
                f"family {family!r} does not expose validate_address"
            )

        # Default safe operation: never sign, broadcast, or open ambient I/O.
        if operation not in {"capabilities", "status", "describe", "noop", "identity"}:
            # Unknown operations fail closed rather than inventing ingest side effects.
            raise InvalidRequestError(
                f"unsupported wallet adapter operation {operation!r}; "
                "supported: capabilities, validate_address"
            )
        return self._capabilities_payload(processor, family)

    def _capabilities_payload(self, processor: Any, family: str) -> dict[str, Any]:
        declared = self._registry.capabilities_for(family)
        live: Mapping[str, Any] | None = None
        if hasattr(processor, "get_capabilities") and callable(processor.get_capabilities):
            raw = processor.get_capabilities()
            if isinstance(raw, Mapping):
                live = dict(raw)
        elif hasattr(processor, "capabilities"):
            caps = processor.capabilities
            if isinstance(caps, Mapping):
                live = dict(caps)
            elif hasattr(caps, "provider"):
                live = {
                    "provider": caps.provider,
                    "chain_namespaces": sorted(getattr(caps, "chain_namespaces", ())),
                    "features": sorted(
                        f.value if hasattr(f, "value") else str(f)
                        for f in getattr(caps, "features", ())
                    ),
                    "metadata": dict(getattr(caps, "metadata", {}) or {}),
                }

        return {
            "family": family,
            "extra": self._registry.required_extra(family),
            "declared": {
                "provider": declared.provider,
                "chain_namespaces": sorted(declared.chain_namespaces),
                "features": sorted(f.value for f in declared.features),
                "metadata": dict(declared.metadata),
            },
            "live": live,
            "limits_default": {
                "max_items": RequestLimits().max_items,
                "max_pages": RequestLimits().max_pages,
                "max_requests": RequestLimits().max_requests,
                "max_response_bytes": RequestLimits().max_response_bytes,
            },
            "composes": sorted(self._registry.get_spec(family).composes),
            "signing": False,
            "broadcast": False,
        }


__all__ = [
    "ADAPTER_GENERIC_API",
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "LEGACY_CAN_PROCESS_WIRED",
    "WalletProcessorProtocolAdapter",
]
