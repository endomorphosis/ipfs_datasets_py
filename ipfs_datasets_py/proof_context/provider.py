"""Lazy datasets v0.1 port over inventoried canonical implementations."""

from __future__ import annotations

import importlib
from typing import Any, Callable

from ipfs_datasets_py.proof_context.contracts import (
    CANONICAL_CAPABILITIES,
    PORT_INTERFACE,
    PORT_SCHEMA,
    PRODUCER_REPOSITORY,
    CompatibilityError,
    InsufficientContextError,
    OpaqueSourceRequiredError,
    StaleContextError,
    UnavailableContextError,
)

_RESOLVED: dict[str, Any] = {}


def _load(module: str, attr: str) -> Any:
    key = f"{module}:{attr}"
    if key not in _RESOLVED:
        loaded = importlib.import_module(module)
        try:
            _RESOLVED[key] = getattr(loaded, attr)
        except AttributeError as exc:
            raise UnavailableContextError(
                f"canonical symbol {attr} missing from {module}"
            ) from exc
    return _RESOLVED[key]


class DatasetsProofContextProvider:
    """Stable v0.1 port. Does not duplicate analyzers or ContextPack builders."""

    schema = PORT_SCHEMA
    interface = PORT_INTERFACE
    producer = PRODUCER_REPOSITORY
    context_pack_construction_owner = "pending:PCCE-012"

    def capabilities(self) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for name, module, symbol in CANONICAL_CAPABILITIES:
            obj = _load(module, symbol)
            rows.append(
                {
                    "subsystem": name,
                    "module": module,
                    "symbol": symbol,
                    "resolved": getattr(obj, "__qualname__", symbol),
                    "producer": PRODUCER_REPOSITORY,
                }
            )
        return tuple(rows)

    def prove_compatibility(self) -> None:
        for _name, module, symbol in CANONICAL_CAPABILITIES:
            obj = _load(module, symbol)
            if obj is None:
                raise CompatibilityError(f"{symbol} resolved to None in {module}")

    def compile_semantic_capsule(self, *args: Any, **kwargs: Any) -> Any:
        return _load(
            "ipfs_datasets_py.logic.software_contracts.semantic_state.capsules",
            "compile_semantic_capsule",
        )(*args, **kwargs)

    def evaluate_context_sufficiency(self, *args: Any, **kwargs: Any) -> Any:
        return _load(
            "ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency",
            "evaluate_context_sufficiency",
        )(*args, **kwargs)

    def context_pack_view_type(self) -> type:
        return _load(
            "ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency",
            "ContextPackView",
        )

    def build_semantic_state(self, *args: Any, **kwargs: Any) -> Any:
        return _load(
            "ipfs_datasets_py.logic.software_contracts.semantic_state.api",
            "build_semantic_state",
        )(*args, **kwargs)

    def require_fresh(self, status: str) -> None:
        if status == "stale":
            raise StaleContextError("stale semantic state is not v0.1 authority")
        if status == "unavailable":
            raise UnavailableContextError("unavailable capability is not success")
        if status == "insufficient":
            raise InsufficientContextError("insufficient context is not success")
        if status == "opaque":
            raise OpaqueSourceRequiredError(
                "opaque content requires exact scanned-tree source"
            )

    def require_scanned_tree_source(
        self, *, tree_oid: str | None, source_oid: str | None, opaque: bool
    ) -> None:
        if not opaque:
            return
        if not tree_oid or not source_oid or tree_oid != source_oid:
            raise OpaqueSourceRequiredError(
                "opaque or insufficient content requires the exact scanned-tree source"
            )


def get_provider() -> DatasetsProofContextProvider:
    return DatasetsProofContextProvider()


def load_capability(name: str) -> Callable[..., Any]:
    for subsystem, module, symbol in CANONICAL_CAPABILITIES:
        if name in {subsystem, symbol}:
            return _load(module, symbol)
    raise UnavailableContextError(f"unknown datasets v0.1 capability {name!r}")
