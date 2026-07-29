from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ipfs_datasets_py.processors.wallets.errors import ProviderError
from ipfs_datasets_py.processors.wallets.protocols import OperationContext


class FixtureSolanaRpc:
    """Offline Solana JSON-RPC transport backed by one frozen session."""

    def __init__(self, session: Mapping[str, Any]) -> None:
        self.session = session
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def json_rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object] | Sequence[object],
        *,
        context: OperationContext,
        request_id: int | str = 1,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        del url, request_id, headers
        context.check_active()
        arguments = tuple(params)
        self.calls.append((method, arguments))
        if method == "getGenesisHash":
            return self.session["network"]["genesis_hash"]
        if method == "getSlot":
            commitment = arguments[0]["commitment"]
            return self.session["slots"][commitment]
        if method == "getBlock":
            return self.session["blocks"].get(str(arguments[0]))
        if method == "getTransaction":
            return self.session["transactions"].get(str(arguments[0]))
        if method == "getBalance":
            return {"context": {"slot": 100}, "value": 18446744073709551615}
        if method == "getSignaturesForAddress":
            config = arguments[1]
            before = config.get("before")
            if before is None:
                return self.session["signature_pages"]["first"]
            failed = self.session["signatures"]["failed_legacy"]
            if before == failed:
                return self.session["signature_pages"]["after_failed"]
            return []
        raise ProviderError(f"fixture has no response for {method} {arguments!r}")
