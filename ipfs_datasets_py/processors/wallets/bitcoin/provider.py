"""Esplora-style Bitcoin ledger and wallet provider.

One reviewed provider family (Blockstream Esplora REST) is supported first.
The provider is read-only: no PSBT construction, signing, or broadcast.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urljoin

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
from .models import BitcoinTransaction
from .networks import BITCOIN_NAMESPACE, BitcoinNetwork, chain_ref_for
from .normalizer import parse_esplora_transaction
from .scripts import describe_address

PROVIDER_FAMILY = "esplora"
PROVIDER_NAME = "bitcoin-esplora"


class BitcoinResponseBackend(Protocol):
    """Injected response source for offline fixtures or HTTP transport."""

    async def get_json(self, path: str, *, context: OperationContext) -> Any:
        ...


@dataclass
class MappingResponseBackend:
    """Offline backend serving path → JSON payloads (fixtures / fakes)."""

    responses: Mapping[str, Any]
    missing_is_error: bool = True

    async def get_json(self, path: str, *, context: OperationContext) -> Any:
        context.check_active()
        key = path if path.startswith("/") else f"/{path}"
        if key not in self.responses:
            # Allow lookup without leading slash variants.
            alt = key.lstrip("/")
            if alt in self.responses:
                return self.responses[alt]
            if self.missing_is_error:
                raise ProviderError(f"fixture path not found: {key}")
            return None
        return self.responses[key]


@dataclass
class EsploraHttpBackend:
    """Bounded Esplora REST backend over an injected :class:`HttpTransport`."""

    transport: HttpTransport
    base_url: str
    max_response_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        base = self.base_url.rstrip("/") + "/"
        if not base.startswith(("http://", "https://")):
            raise InvalidRequestError("Esplora base_url must use http or https")
        self.base_url = base

    async def get_json(self, path: str, *, context: OperationContext) -> Any:
        context.check_active()
        rel = path.lstrip("/")
        url = urljoin(self.base_url, rel)
        request = HttpRequest(
            method="GET",
            url=url,
            max_response_bytes=min(
                self.max_response_bytes, context.limits.max_response_bytes
            ),
            headers={"accept": "application/json"},
        )
        if hasattr(self.transport, "request_json"):
            return await self.transport.request_json(request, context=context)  # type: ignore[attr-defined]
        response = await self.transport.request(request, context=context)
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Esplora response was not valid JSON") from exc


@dataclass
class BitcoinLedgerProvider:
    """Bounded Bitcoin wallet/ledger source implementing shared protocols.

    Implements both wallet-history and ledger-range ingestion for the Esplora
    provider family. Explicitly does **not** expose PSBT, sign, submit, or
    broadcast capabilities.
    """

    network: BitcoinNetwork = BitcoinNetwork.MAINNET
    backend: BitcoinResponseBackend | None = None
    provider: str = PROVIDER_NAME
    page_size: int = 25

    def __post_init__(self) -> None:
        if not isinstance(self.network, BitcoinNetwork):
            raise InvalidRequestError("network must be a BitcoinNetwork")
        if self.backend is None:
            raise InvalidRequestError(
                "backend is required (EsploraHttpBackend or MappingResponseBackend)"
            )
        if (
            isinstance(self.page_size, bool)
            or not isinstance(self.page_size, int)
            or self.page_size <= 0
        ):
            raise InvalidRequestError("page_size must be a positive integer")
        self._chain = chain_ref_for(self.network)
        self._request_count = 0
        self._capabilities = Capabilities(
            provider=self.provider,
            chain_namespaces=frozenset({BITCOIN_NAMESPACE, self.network.value}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.BALANCES,
                    Capability.FINALITY,
                    Capability.REORG_RECOVERY,
                    Capability.RAW_PAYLOADS,
                }
            ),
            metadata={
                "provider_family": PROVIDER_FAMILY,
                "network": self.network.value,
                "genesis_hash": self._chain.genesis_hash,
                "utxo_model": True,
                "supports_psbt": False,
                "supports_sign": False,
                "supports_broadcast": False,
                "ownership_clustering": False,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    async def _get(self, path: str, *, context: OperationContext) -> Any:
        context.check_active()
        self._request_count += 1
        if self._request_count > context.limits.max_requests:
            raise ResourceLimitError("Bitcoin provider exceeded max_requests")
        assert self.backend is not None
        return await self.backend.get_json(path, context=context)

    async def validate_address(
        self,
        address: str,
        *,
        context: OperationContext,
    ) -> object:
        """Validate address for the configured network (no I/O)."""

        context.check_active()
        descriptor = describe_address(address, network=self.network)
        return {
            "address": descriptor.address,
            "script_type": descriptor.script_type.value,
            "network": self.network.value,
            "chain": self._chain.to_dict(),
            "descriptor": descriptor.to_dict(),
        }

    async def ledger_head(self, *, context: OperationContext) -> object:
        """Return tip height and hash from Esplora."""

        context.check_active()
        height = await self._get("/blocks/tip/height", context=context)
        tip_hash = await self._get("/blocks/tip/hash", context=context)
        try:
            height_int = int(height)
        except (TypeError, ValueError) as exc:
            raise ProviderError("invalid tip height from Esplora") from exc
        tip = str(tip_hash).strip().lower()
        if not tip:
            raise ProviderError("invalid tip hash from Esplora")
        return {
            "sequence": height_int,
            "hash": tip,
            "network": self.network.value,
            "genesis_hash": self._chain.genesis_hash,
        }

    def ingest_wallet(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._ingest_wallet(request)

    async def _ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        address = str(request.scope).strip()
        if not address:
            raise InvalidRequestError("wallet scope must be an address")
        # Fail closed on network mismatch before any list call.
        await self.validate_address(address, context=request.context)

        last_seen = request.cursor
        pages = 0
        items = 0
        encoded = quote(address, safe="")

        while pages < request.context.limits.max_pages:
            request.context.check_active()
            if last_seen:
                path = f"/address/{encoded}/txs/chain/{last_seen}"
            else:
                path = f"/address/{encoded}/txs"
            payload = await self._get(path, context=request.context)
            if payload is None:
                break
            if not isinstance(payload, list):
                raise ProviderError("Esplora address txs must be a list")
            if not payload:
                break

            records: list[BitcoinTransaction] = []
            raw_bytes = 0
            for item in payload:
                if not isinstance(item, Mapping):
                    raise ProviderError("Esplora tx entry must be a mapping")
                tx = parse_esplora_transaction(item, network=self.network)
                records.append(tx)
                raw_bytes += len(
                    json.dumps(item, separators=(",", ":"), sort_keys=True).encode()
                )
                last_seen = tx.txid
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
            # Esplora returns up to 25 txs; fewer means end.
            next_cursor = last_seen if len(payload) >= min(self.page_size, 25) else None
            batch = RecordBatch(
                records=tuple(records),
                next_cursor=next_cursor,
                response_bytes=raw_bytes,
            )
            batch.enforce(request.context.limits)
            yield batch
            if next_cursor is None:
                return
            if pages >= request.context.limits.max_pages:
                return

    def ingest_ledger(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._ingest_ledger(request)

    async def _ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        start = request.start_position
        end = request.end_position
        if start is None or end is None:
            raise InvalidRequestError(
                "ledger ingestion requires start_position and end_position"
            )
        if start > end:
            raise InvalidRequestError("start_position must not exceed end_position")

        cursor_height = start
        if request.cursor:
            try:
                cursor_height = int(request.cursor)
            except ValueError as exc:
                raise InvalidRequestError("ledger cursor must be an integer height") from exc

        pages = 0
        items = 0
        height = cursor_height
        while height <= end and pages < request.context.limits.max_pages:
            request.context.check_active()
            block_hash = await self._get(f"/block-height/{height}", context=request.context)
            block_hash_s = str(block_hash).strip().lower()
            if not block_hash_s:
                raise ProviderError(f"missing block hash at height {height}")
            # Prefer /block/{hash}/txs when available; fall back to single-page list.
            txs_payload = await self._get(
                f"/block/{block_hash_s}/txs", context=request.context
            )
            if not isinstance(txs_payload, list):
                raise ProviderError("Esplora block txs must be a list")
            records: list[BitcoinTransaction] = []
            raw_bytes = 0
            for item in txs_payload:
                if not isinstance(item, Mapping):
                    raise ProviderError("Esplora tx entry must be a mapping")
                tx = parse_esplora_transaction(item, network=self.network)
                records.append(tx)
                raw_bytes += len(
                    json.dumps(item, separators=(",", ":"), sort_keys=True).encode()
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
            next_height = height + 1
            next_cursor = str(next_height) if next_height <= end else None
            batch = RecordBatch(
                records=tuple(records),
                next_cursor=next_cursor,
                response_bytes=raw_bytes,
            )
            batch.enforce(request.context.limits)
            yield batch
            if next_cursor is None:
                return
            height = next_height

    async def address_utxos(
        self,
        address: str,
        *,
        context: OperationContext,
    ) -> tuple[Mapping[str, Any], ...]:
        """Fetch Esplora UTXO set for an address (read-only)."""

        await self.validate_address(address, context=context)
        encoded = quote(address, safe="")
        payload = await self._get(f"/address/{encoded}/utxo", context=context)
        if not isinstance(payload, list):
            raise ProviderError("Esplora utxo response must be a list")
        return tuple(item for item in payload if isinstance(item, Mapping))


def fixture_backend_from_transactions(
    transactions: Sequence[Mapping[str, Any]],
    *,
    tip_height: int,
    tip_hash: str,
    address_index: Mapping[str, Sequence[str]] | None = None,
    blocks: Mapping[int, str] | None = None,
) -> MappingResponseBackend:
    """Build an offline Esplora backend from fixture transactions."""

    by_txid = {
        str(tx["txid"]).lower(): tx
        for tx in transactions
        if isinstance(tx, Mapping) and "txid" in tx
    }
    responses: MutableMapping[str, Any] = {
        "/blocks/tip/height": tip_height,
        "/blocks/tip/hash": tip_hash,
    }
    for txid, tx in by_txid.items():
        responses[f"/tx/{txid}"] = tx

    if blocks:
        for height, block_hash in blocks.items():
            responses[f"/block-height/{int(height)}"] = block_hash
            height_txs = [
                by_txid[txid]
                for txid, tx in by_txid.items()
                if (tx.get("status") or {}).get("block_height") == height
            ]
            # Preserve insertion order from transactions sequence.
            ordered = [
                tx
                for tx in transactions
                if (tx.get("status") or {}).get("block_height") == height
            ]
            responses[f"/block/{block_hash}/txs"] = ordered or height_txs

    if address_index:
        for address, txids in address_index.items():
            encoded = quote(address, safe="")
            txs = [by_txid[t.lower()] for t in txids if t.lower() in by_txid]
            responses[f"/address/{encoded}/txs"] = txs
            responses[f"/address/{encoded}/utxo"] = _utxos_for_address(txs, address)

    return MappingResponseBackend(responses=dict(responses))


def _utxos_for_address(
    transactions: Sequence[Mapping[str, Any]],
    address: str,
) -> list[dict[str, Any]]:
    spent: set[str] = set()
    created: list[dict[str, Any]] = []
    for tx in transactions:
        txid = str(tx.get("txid", "")).lower()
        for vin in tx.get("vin") or []:
            if not isinstance(vin, Mapping) or vin.get("is_coinbase"):
                continue
            prev = f"{str(vin.get('txid', '')).lower()}:{int(vin.get('vout', -1))}"
            spent.add(prev)
        for index, vout in enumerate(tx.get("vout") or []):
            if not isinstance(vout, Mapping):
                continue
            if vout.get("scriptpubkey_address") != address:
                continue
            n = int(vout.get("n", index))
            created.append(
                {
                    "txid": txid,
                    "vout": n,
                    "value": vout.get("value"),
                    "status": tx.get("status") or {},
                }
            )
    return [
        item
        for item in created
        if f"{item['txid']}:{item['vout']}" not in spent
    ]


__all__ = [
    "PROVIDER_FAMILY",
    "PROVIDER_NAME",
    "BitcoinLedgerProvider",
    "BitcoinResponseBackend",
    "EsploraHttpBackend",
    "MappingResponseBackend",
    "fixture_backend_from_transactions",
]
