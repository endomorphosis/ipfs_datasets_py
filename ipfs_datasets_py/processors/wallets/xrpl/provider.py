"""XRPL JSON-RPC ledger and account provider.

Implements ``account_tx`` marker pagination, ledger head continuity, and
read-only account inspection. Explicitly does **not** expose sign, submit,
or payment construction. Xaman wallet/payload APIs are out of scope.

AST entry: ``XRPLLedgerProvider``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

from ..errors import InvalidRequestError, ProviderError, ResourceLimitError
from ..protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    HttpRequest,
    HttpTransport,
    OperationContext,
    RecordBatch,
)
from .accounts import validate_classic_address
from .models import XRPLTransaction
from .networks import XRPL_NAMESPACE, XRPLNetwork, chain_ref_for
from .normalizer import parse_account_tx_entry
from .privacy import MemoPrivacyPolicy

PROVIDER_FAMILY = "xrpl-json-rpc"
PROVIDER_NAME = "xrpl-json-rpc"


class XRPLResponseBackend(Protocol):
    """Injected response source for offline fixtures or HTTP JSON-RPC."""

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        context: OperationContext,
    ) -> Any:
        ...


def _marker_key(marker: Any) -> str:
    """Canonical JSON for a marker object or string (stable pagination)."""

    if marker is None:
        return ""
    if isinstance(marker, str):
        return marker
    return json.dumps(marker, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass
class MappingResponseBackend:
    """Offline backend serving method+params keys → JSON result payloads."""

    responses: Mapping[str, Any]
    missing_is_error: bool = True

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        context: OperationContext,
    ) -> Any:
        context.check_active()
        key = _fixture_key(method, params)
        if key in self.responses:
            return self.responses[key]
        # Flexible account_tx lookup: match account + marker (limit may vary).
        if method == "account_tx" and params is not None:
            account = params.get("account")
            marker = params.get("marker")
            for stored_key, value in self.responses.items():
                try:
                    parsed = json.loads(stored_key)
                except (TypeError, json.JSONDecodeError):
                    continue
                if parsed.get("method") != "account_tx":
                    continue
                stored_params = parsed.get("params") or {}
                if stored_params.get("account") != account:
                    continue
                stored_marker = stored_params.get("marker")
                if _marker_key(stored_marker) == _marker_key(marker):
                    return value
        if self.missing_is_error:
            raise ProviderError(f"fixture method not found: {key}")
        return None


@dataclass
class JsonRpcHttpBackend:
    """Bounded XRPL JSON-RPC over an injected :class:`HttpTransport`."""

    transport: HttpTransport
    base_url: str
    max_response_bytes: int = 16 * 1024 * 1024
    request_id: int = 1

    def __post_init__(self) -> None:
        base = self.base_url.rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise InvalidRequestError("XRPL JSON-RPC base_url must use http or https")
        self.base_url = base

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        context: OperationContext,
    ) -> Any:
        context.check_active()
        payload = {
            "method": method,
            "params": [dict(params or {})],
            "id": self.request_id,
            "jsonrpc": "2.0",
        }
        self.request_id += 1
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request = HttpRequest(
            method="POST",
            url=self.base_url,
            max_response_bytes=min(
                self.max_response_bytes, context.limits.max_response_bytes
            ),
            headers={"accept": "application/json", "content-type": "application/json"},
            body=body,
        )
        if hasattr(self.transport, "request_json"):
            data = await self.transport.request_json(request, context=context)  # type: ignore[attr-defined]
        else:
            response = await self.transport.request(request, context=context)
            try:
                data = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("XRPL response was not valid JSON") from exc
        if not isinstance(data, Mapping):
            raise ProviderError("XRPL JSON-RPC response must be a mapping")
        if data.get("error"):
            raise ProviderError("XRPL JSON-RPC returned an error")
        result = data.get("result")
        if result is None:
            raise ProviderError("XRPL JSON-RPC missing result")
        return result


def _fixture_key(method: str, params: Mapping[str, Any] | None) -> str:
    marker = None
    if params:
        marker = params.get("marker")
    parts = {
        "method": method,
        "params": dict(params or {}),
    }
    # Normalize marker for keying.
    if marker is not None:
        parts["params"]["marker"] = json.loads(_marker_key(marker)) if not isinstance(
            marker, str
        ) else marker
    return json.dumps(parts, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass
class XRPLLedgerProvider:
    """Bounded XRPL account/ledger source implementing shared protocols.

    Marker pagination is deterministic: each page advances solely by the
    server-provided marker, and seen transaction hashes are tracked to reject
    duplicates. Only ``validated=true`` results are treated as final by the
    normalizer; this provider surfaces the validated flag as returned.

    No signing, submission, or Xaman payload capability is exposed.
    """

    network: XRPLNetwork = XRPLNetwork.MAINNET
    backend: XRPLResponseBackend | None = None
    provider: str = PROVIDER_NAME
    page_size: int = 20
    privacy: MemoPrivacyPolicy | None = None
    require_validated: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be an XRPLNetwork")
        if self.backend is None:
            raise InvalidRequestError(
                "backend is required (JsonRpcHttpBackend or MappingResponseBackend)"
            )
        if (
            isinstance(self.page_size, bool)
            or not isinstance(self.page_size, int)
            or self.page_size <= 0
        ):
            raise InvalidRequestError("page_size must be a positive integer")
        self._chain = chain_ref_for(self.network)
        self._request_count = 0
        self._privacy = self.privacy or MemoPrivacyPolicy()
        self._capabilities = Capabilities(
            provider=self.provider,
            chain_namespaces=frozenset({XRPL_NAMESPACE, self.network.value}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.BALANCES,
                    Capability.TOKEN_TRANSFERS,
                    Capability.FINALITY,
                    Capability.REORG_RECOVERY,
                    Capability.RAW_PAYLOADS,
                }
            ),
            metadata={
                "provider_family": PROVIDER_FAMILY,
                "network": self.network.value,
                "network_id": self._chain.chain_id,
                "genesis_hash": self._chain.genesis_hash,
                "account_model": True,
                "supports_sign": False,
                "supports_submit": False,
                "supports_broadcast": False,
                "xaman_payloads": False,
                "marker_pagination": True,
                "require_validated": self.require_validated,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    async def _call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        context: OperationContext,
    ) -> Any:
        context.check_active()
        self._request_count += 1
        if self._request_count > context.limits.max_requests:
            raise ResourceLimitError("XRPL provider exceeded max_requests")
        assert self.backend is not None
        return await self.backend.call(method, params, context=context)

    async def validate_address(
        self,
        address: str,
        *,
        context: OperationContext,
    ) -> object:
        """Validate classic account for the configured network (no I/O)."""

        context.check_active()
        descriptor = validate_classic_address(address, network=self.network)
        return {
            "address": descriptor.address,
            "encoding": descriptor.encoding.value,
            "network": self.network.value,
            "chain": self._chain.to_dict(),
            "descriptor": descriptor.to_dict(),
        }

    async def ledger_head(self, *, context: OperationContext) -> object:
        """Return validated ledger index and hash for checkpoint continuity."""

        context.check_active()
        result = await self._call(
            "ledger",
            {"ledger_index": "validated", "transactions": False},
            context=context,
        )
        if not isinstance(result, Mapping):
            raise ProviderError("ledger result must be a mapping")
        ledger = result.get("ledger") or result
        if not isinstance(ledger, Mapping):
            raise ProviderError("ledger object missing")
        index = ledger.get("ledger_index") or ledger.get("seqNum")
        ledger_hash = ledger.get("ledger_hash") or ledger.get("hash")
        if index is None or not ledger_hash:
            raise ProviderError("ledger head missing index or hash")
        try:
            index_int = int(index)
        except (TypeError, ValueError) as exc:
            raise ProviderError("invalid ledger index") from exc
        # Continuity anchors for checkpoints.
        parent_hash = ledger.get("parent_hash") or ledger.get("parentHash")
        return {
            "sequence": index_int,
            "hash": str(ledger_hash).upper(),
            "parent_hash": str(parent_hash).upper() if parent_hash else None,
            "network": self.network.value,
            "genesis_hash": self._chain.genesis_hash,
            "validated": True,
        }

    def ingest_wallet(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._ingest_wallet(request)

    async def _ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        """Stream ``account_tx`` pages using marker pagination without gaps/dupes."""

        request.context.check_active()
        account = str(request.scope).strip()
        if not account:
            raise InvalidRequestError("wallet scope must be an XRPL account")
        await self.validate_address(account, context=request.context)

        marker: Any | None = None
        if request.cursor:
            try:
                marker = json.loads(request.cursor)
            except json.JSONDecodeError:
                marker = request.cursor

        seen_hashes: set[str] = set()
        pages = 0
        items = 0
        ledger_min = request.start_position if request.start_position is not None else -1
        ledger_max = request.end_position if request.end_position is not None else -1

        while pages < request.context.limits.max_pages:
            request.context.check_active()
            params: dict[str, Any] = {
                "account": account,
                "ledger_index_min": ledger_min,
                "ledger_index_max": ledger_max,
                "limit": min(self.page_size, request.context.limits.max_items - items or self.page_size),
                "forward": bool(request.options.get("forward", False)),
            }
            if self.require_validated:
                # Request only validated history when the server supports it.
                params["ledger_index"] = "validated"
            if marker is not None:
                params["marker"] = marker

            result = await self._call("account_tx", params, context=request.context)
            if result is None:
                break
            if not isinstance(result, Mapping):
                raise ProviderError("account_tx result must be a mapping")

            txs = result.get("transactions") or []
            if not isinstance(txs, list):
                raise ProviderError("account_tx.transactions must be a list")

            records: list[XRPLTransaction] = []
            raw_bytes = 0
            for entry in txs:
                if not isinstance(entry, Mapping):
                    raise ProviderError("account_tx entry must be a mapping")
                # Force validated default from top-level when present.
                validated_hint = result.get("validated")
                if "validated" not in entry and validated_hint is not None:
                    entry = dict(entry)
                    entry["validated"] = bool(validated_hint)
                if self.require_validated and entry.get("validated") is False:
                    # Skip unvalidated; do not treat as final.
                    continue
                tx = parse_account_tx_entry(
                    entry,
                    network=self.network,
                    privacy=self._privacy,
                )
                if tx.hash in seen_hashes:
                    raise ProviderError(
                        f"duplicate transaction hash in marker pagination: {tx.hash}"
                    )
                seen_hashes.add(tx.hash)
                records.append(tx)
                raw_bytes += len(
                    json.dumps(entry, separators=(",", ":"), sort_keys=True).encode()
                )
                items += 1
                if items >= request.context.limits.max_items:
                    batch = RecordBatch(
                        records=tuple(records),
                        next_cursor=None,
                        response_bytes=raw_bytes,
                    )
                    batch.enforce(request.context.limits)
                    yield batch
                    return

            pages += 1
            next_marker = result.get("marker")
            next_cursor = (
                _marker_key(next_marker) if next_marker is not None else None
            )
            batch = RecordBatch(
                records=tuple(records),
                next_cursor=next_cursor,
                response_bytes=raw_bytes,
            )
            batch.enforce(request.context.limits)
            yield batch
            if next_marker is None:
                return
            marker = next_marker
            if pages >= request.context.limits.max_pages:
                return

    def ingest_ledger(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._ingest_ledger(request)

    async def _ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        """Ingest validated ledgers in an inclusive index range with hash anchors."""

        request.context.check_active()
        start = request.start_position
        end = request.end_position
        if start is None or end is None:
            raise InvalidRequestError(
                "ledger ingestion requires start_position and end_position"
            )
        if start > end:
            raise InvalidRequestError("start_position must not exceed end_position")

        cursor_index = start
        if request.cursor:
            try:
                cursor_index = int(request.cursor)
            except ValueError as exc:
                raise InvalidRequestError(
                    "ledger cursor must be an integer ledger index"
                ) from exc

        pages = 0
        items = 0
        index = cursor_index
        prev_hash: str | None = None

        while index <= end and pages < request.context.limits.max_pages:
            request.context.check_active()
            result = await self._call(
                "ledger",
                {
                    "ledger_index": index,
                    "transactions": True,
                    "expand": True,
                },
                context=request.context,
            )
            if not isinstance(result, Mapping):
                raise ProviderError("ledger result must be a mapping")
            if result.get("validated") is False and self.require_validated:
                raise ProviderError(
                    f"ledger {index} is not validated; refusing non-final range ingest"
                )
            ledger = result.get("ledger") or result
            if not isinstance(ledger, Mapping):
                raise ProviderError("ledger object missing")
            ledger_hash = str(ledger.get("ledger_hash") or ledger.get("hash") or "").upper()
            parent_hash = ledger.get("parent_hash") or ledger.get("parentHash")
            if prev_hash is not None and parent_hash is not None:
                if str(parent_hash).upper() != prev_hash:
                    raise ProviderError(
                        f"ledger hash continuity broken at index {index}: "
                        f"parent_hash mismatch"
                    )
            prev_hash = ledger_hash or prev_hash

            txs = ledger.get("transactions") or []
            if not isinstance(txs, list):
                raise ProviderError("ledger.transactions must be a list")

            records: list[XRPLTransaction] = []
            raw_bytes = 0
            for entry in txs:
                if isinstance(entry, str):
                    # Hash-only expansion; skip without body.
                    continue
                if not isinstance(entry, Mapping):
                    raise ProviderError("ledger tx entry must be a mapping")
                # Wrap expanded tx into account_tx-like shape.
                if "tx" not in entry and "TransactionType" in entry:
                    wrapped = {
                        "tx": entry,
                        "meta": entry.get("metaData") or entry.get("meta"),
                        "validated": True,
                        "ledger_index": index,
                        "ledger_hash": ledger_hash,
                    }
                else:
                    wrapped = dict(entry)
                    wrapped.setdefault("validated", True)
                    wrapped.setdefault("ledger_index", index)
                    wrapped.setdefault("ledger_hash", ledger_hash)
                tx = parse_account_tx_entry(
                    wrapped,
                    network=self.network,
                    privacy=self._privacy,
                    validated_hint=True,
                )
                records.append(tx)
                raw_bytes += len(
                    json.dumps(entry, separators=(",", ":"), sort_keys=True).encode()
                )
                items += 1
                if items >= request.context.limits.max_items:
                    batch = RecordBatch(
                        records=tuple(records),
                        next_cursor=None,
                        response_bytes=raw_bytes,
                    )
                    batch.enforce(request.context.limits)
                    yield batch
                    return

            pages += 1
            next_index = index + 1
            next_cursor = str(next_index) if next_index <= end else None
            batch = RecordBatch(
                records=tuple(records),
                next_cursor=next_cursor,
                response_bytes=raw_bytes,
            )
            batch.enforce(request.context.limits)
            yield batch
            if next_cursor is None:
                return
            index = next_index


def fixture_backend_from_account_tx(
    pages: Sequence[Mapping[str, Any]],
    *,
    account: str,
    ledger_head: Mapping[str, Any] | None = None,
    ledgers: Mapping[int, Mapping[str, Any]] | None = None,
) -> MappingResponseBackend:
    """Build an offline JSON-RPC backend from ordered ``account_tx`` pages.

    Each page mapping should look like the XRPL ``result`` object::

        {
          "account": "...",
          "transactions": [...],
          "marker": {...} | null,
          "validated": true
        }

    Pages are chained by marker: page 0 has no marker key in the request;
    subsequent pages are keyed by the previous page's marker.
    """

    responses: MutableMapping[str, Any] = {}
    if ledger_head is not None:
        responses[
            _fixture_key("ledger", {"ledger_index": "validated", "transactions": False})
        ] = ledger_head

    if ledgers:
        for idx, ledger_result in ledgers.items():
            responses[
                _fixture_key(
                    "ledger",
                    {"ledger_index": int(idx), "transactions": True, "expand": True},
                )
            ] = ledger_result

    prev_marker: Any | None = None
    for page in pages:
        if not isinstance(page, Mapping):
            raise InvalidRequestError("account_tx page must be a mapping")
        params: dict[str, Any] = {
            "account": account,
            "ledger_index_min": page.get("ledger_index_min", -1),
            "ledger_index_max": page.get("ledger_index_max", -1),
            "limit": page.get("limit", 20),
            "forward": page.get("forward", False),
            "ledger_index": "validated",
        }
        if prev_marker is not None:
            params["marker"] = prev_marker
        responses[_fixture_key("account_tx", params)] = page
        prev_marker = page.get("marker")

    return MappingResponseBackend(responses=dict(responses))


__all__ = [
    "PROVIDER_FAMILY",
    "PROVIDER_NAME",
    "JsonRpcHttpBackend",
    "MappingResponseBackend",
    "XRPLLedgerProvider",
    "XRPLResponseBackend",
    "fixture_backend_from_account_tx",
]
