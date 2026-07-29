from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ipfs_datasets_py.processors.wallets.errors import ProviderError
from ipfs_datasets_py.processors.wallets.protocols import OperationContext


class FixtureJsonRpc:
    """Offline JSON-RPC transport backed by one frozen session."""

    def __init__(
        self,
        session: Mapping[str, Any],
        *,
        explicit_tags: bool = True,
        traces: bool = True,
    ) -> None:
        self.session = session
        self.explicit_tags = explicit_tags
        self.traces = traces
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
        if method == "eth_chainId":
            return self.session["chain_id_result"]
        if method == "eth_getBalance":
            return self.session["balance_result"]
        if method == "eth_getBlockByNumber":
            tag = arguments[0]
            if tag == "0x0":
                return self.session["genesis"]
            if tag == "0x10":
                return self.session["block"]
            if tag == "latest":
                return self.session["latest"]
            if tag in {"safe", "finalized"}:
                if not self.explicit_tags:
                    raise ProviderError("unsupported block tag")
                return self.session[str(tag)]
        if method == "eth_getTransactionReceipt":
            return self.session["receipts"].get(str(arguments[0]))
        if method == "trace_transaction":
            if not self.traces:
                raise ProviderError("trace API unavailable")
            return self.session["traces"].get(str(arguments[0]), [])
        raise ProviderError(f"fixture has no response for {method} {arguments!r}")
