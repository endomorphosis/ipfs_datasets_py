"""Shared helpers for wallet processor MCP tools.

MCP callers are treated as **untrusted**: provider URLs and secret references
are rejected unless they match the process allowlist configured via
environment variables or explicit tool arguments that only expand allowlists
(never inline secrets).
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from ipfs_datasets_py.processors.wallets.api import (
    ScanBounds,
    TrustLevel,
    TrustPolicy,
    WalletProcessorAPI,
)
from ipfs_datasets_py.processors.wallets.errors import InvalidRequestError
from ipfs_datasets_py.processors.wallets.models import ChainRef


def _split_csv(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def default_trust_policy(
    *,
    extra_hosts: list[str] | None = None,
    extra_secret_prefixes: list[str] | None = None,
) -> TrustPolicy:
    hosts = set(_split_csv(os.environ.get("WALLET_PROCESSOR_MCP_ALLOWED_HOSTS")))
    prefixes = set(
        _split_csv(os.environ.get("WALLET_PROCESSOR_MCP_ALLOWED_SECRET_PREFIXES"))
    )
    if extra_hosts:
        hosts.update(h.strip().lower() for h in extra_hosts if h and h.strip())
    if extra_secret_prefixes:
        prefixes.update(p for p in extra_secret_prefixes if p)
    return TrustPolicy(
        allowed_provider_hosts=frozenset(hosts),
        allowed_secret_prefixes=frozenset(prefixes),
        allow_http=os.environ.get("WALLET_PROCESSOR_MCP_ALLOW_HTTP", "").lower()
        in {"1", "true", "yes"},
    )


_PROCESS_API: WalletProcessorAPI | None = None


def reset_mcp_api() -> None:
    """Drop the process-shared MCP API (tests only)."""

    global _PROCESS_API
    _PROCESS_API = None


def mcp_api(
    *,
    extra_hosts: list[str] | None = None,
    extra_secret_prefixes: list[str] | None = None,
    processor: Any | None = None,
    shared: bool = True,
) -> WalletProcessorAPI:
    """Return an API instance that forces untrusted MCP allowlist checks.

    By default a process-shared instance is reused so status/resume can see
    jobs created by earlier tool calls in the same MCP server process.
    """

    global _PROCESS_API
    policy = default_trust_policy(
        extra_hosts=extra_hosts,
        extra_secret_prefixes=extra_secret_prefixes,
    )
    if processor is not None or not shared:
        return WalletProcessorAPI(
            processor=processor,
            trust_policy=policy,
            trust=TrustLevel.UNTRUSTED,
        )
    if _PROCESS_API is None:
        _PROCESS_API = WalletProcessorAPI(
            trust_policy=policy,
            trust=TrustLevel.UNTRUSTED,
        )
    else:
        # Refresh allowlists from env/args without dropping job state.
        _PROCESS_API._trust_policy = policy  # noqa: SLF001 — intentional
        _PROCESS_API._trust = TrustLevel.UNTRUSTED  # noqa: SLF001
    return _PROCESS_API


def parse_chain(payload: Mapping[str, Any] | None) -> ChainRef:
    if not isinstance(payload, Mapping):
        raise InvalidRequestError("chain must be an object")
    namespace = payload.get("namespace") or payload.get("chain_namespace") or ""
    return ChainRef(
        namespace=str(namespace).strip(),
        network=str(payload.get("network") or "").strip(),
        chain_id=str(payload.get("chain_id") or "").strip(),
        genesis_hash=str(payload.get("genesis_hash") or "").strip(),
    )


def parse_bounds(payload: Mapping[str, Any] | None) -> ScanBounds:
    if payload is None:
        return ScanBounds()
    if not isinstance(payload, Mapping):
        raise InvalidRequestError("bounds must be an object")
    return ScanBounds(
        max_items=int(payload.get("max_items", 1_000)),
        max_pages=int(payload.get("max_pages", 100)),
        max_requests=int(payload.get("max_requests", 100)),
        max_response_bytes=int(payload.get("max_response_bytes", 16 * 1024 * 1024)),
        max_time_seconds=float(payload.get("max_time_seconds", 300)),
        max_retries=int(payload.get("max_retries", 3)),
    )


def error_response(exc: BaseException) -> dict[str, Any]:
    return {
        "status": "error",
        "error": type(exc).__name__,
        "message": str(exc),
    }


def success_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a successful tool result.

    API receipts already carry an operation ``status`` (complete/partial/...).
    That value is moved to ``operation_status`` so MCP callers can rely on
    top-level ``status`` being ``success`` or ``error``.
    """

    out = dict(payload)
    if "status" in out:
        out["operation_status"] = out.pop("status")
    out["status"] = "success"
    return out
