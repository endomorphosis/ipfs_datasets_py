"""Read-only Xaman payload metadata provider.

Fetches payload lifecycle metadata over an injected HTTP transport or offline
fixture backend. Explicitly does **not** expose approve, sign, or submit.
Optional API credentials are secret references only — never logged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urljoin

from ..errors import InvalidRequestError, ProviderError
from ..protocols import (
    Capabilities,
    Capability,
    HttpRequest,
    HttpTransport,
    OperationContext,
    RecordBatch,
)
from ..xrpl.networks import XRPLNetwork, chain_ref_for
from .models import XamanPayload
from .normalizer import parse_xaman_payload
from .privacy import PayloadPrivacyPolicy

PROVIDER_FAMILY = "xaman-http"
PROVIDER_NAME = "xaman-payload-http"
DEFAULT_API_BASE = "https://xumm.app/api/v1/"


class XamanResponseBackend(Protocol):
    """Injected response source for offline fixtures or HTTP."""

    async def get_payload(
        self,
        payload_uuid: str,
        *,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        ...

    async def list_payloads(
        self,
        *,
        cursor: str | None,
        limit: int,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        ...


@dataclass
class MappingPayloadBackend:
    """Offline backend: uuid → payload document (+ optional list pages)."""

    payloads: Mapping[str, Mapping[str, Any]]
    list_pages: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    missing_is_error: bool = True

    async def get_payload(
        self,
        payload_uuid: str,
        *,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        context.check_active()
        key = payload_uuid.strip()
        if key in self.payloads:
            return self.payloads[key]
        # Case-insensitive uuid match.
        for stored, value in self.payloads.items():
            if stored.lower() == key.lower():
                return value
        if self.missing_is_error:
            raise ProviderError(f"fixture payload not found: {payload_uuid}")
        return {}

    async def list_payloads(
        self,
        *,
        cursor: str | None,
        limit: int,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        context.check_active()
        if not self.list_pages:
            items = list(self.payloads.values())[: max(1, limit)]
            return {"payloads": items, "cursor": None, "has_more": False}
        index = 0
        if cursor:
            try:
                index = int(cursor)
            except ValueError as exc:
                raise ProviderError(f"invalid list cursor: {cursor!r}") from exc
        if index < 0 or index >= len(self.list_pages):
            return {"payloads": [], "cursor": None, "has_more": False}
        page = self.list_pages[index]
        next_index = index + 1
        has_more = next_index < len(self.list_pages)
        return {
            "payloads": list(page.get("payloads") or page.get("items") or []),
            "cursor": str(next_index) if has_more else None,
            "has_more": has_more,
        }


@dataclass
class HttpPayloadBackend:
    """Bounded Xaman REST GETs over an injected :class:`HttpTransport`."""

    transport: HttpTransport
    base_url: str = DEFAULT_API_BASE
    api_key_header: str = "X-API-Key"
    api_key_value: str | None = None
    api_secret_header: str = "X-API-Secret"
    api_secret_value: str | None = None
    max_response_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        base = self.base_url.rstrip("/") + "/"
        if not base.startswith(("http://", "https://")):
            raise InvalidRequestError("Xaman base_url must use http or https")
        self.base_url = base

    async def get_payload(
        self,
        payload_uuid: str,
        *,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        context.check_active()
        uuid = payload_uuid.strip()
        if not uuid:
            raise InvalidRequestError("payload_uuid must not be empty")
        url = urljoin(self.base_url, f"platform/payload/{uuid}")
        response = await self.transport.request(
            HttpRequest(
                method="GET",
                url=url,
                headers=self._headers(),
                max_response_bytes=self.max_response_bytes,
            ),
            context=context,
        )
        return _decode_json_mapping(response.body, label="payload")

    async def list_payloads(
        self,
        *,
        cursor: str | None,
        limit: int,
        context: OperationContext,
    ) -> Mapping[str, Any]:
        context.check_active()
        path = "platform/payloads"
        query = f"?limit={int(limit)}"
        if cursor:
            query += f"&cursor={cursor}"
        url = urljoin(self.base_url, path + query)
        response = await self.transport.request(
            HttpRequest(
                method="GET",
                url=url,
                headers=self._headers(),
                max_response_bytes=self.max_response_bytes,
            ),
            context=context,
        )
        return _decode_json_mapping(response.body, label="payload_list")

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        # Values may be secret-ref strings; transport policy handles resolution.
        if self.api_key_value:
            headers[self.api_key_header] = self.api_key_value
        if self.api_secret_value:
            headers[self.api_secret_header] = self.api_secret_value
        return headers


@dataclass
class XamanPayloadProvider:
    """Read-only provider for Xaman payload metadata ingestion."""

    network: XRPLNetwork = XRPLNetwork.MAINNET
    backend: XamanResponseBackend | None = None
    privacy: PayloadPrivacyPolicy | None = None
    name: str = PROVIDER_NAME
    page_size: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be XRPLNetwork")
        if (
            isinstance(self.page_size, bool)
            or not isinstance(self.page_size, int)
            or self.page_size <= 0
        ):
            raise InvalidRequestError("page_size must be a positive integer")
        self._chain = chain_ref_for(self.network)
        self._privacy = self.privacy or PayloadPrivacyPolicy()
        self._capabilities = Capabilities(
            provider=self.name,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(
                {
                    Capability.RAW_PAYLOADS,
                    Capability.DATASET_EXPORT,
                }
            ),
            metadata={
                "network": self.network.value,
                "provider_family": PROVIDER_FAMILY,
                "xaman_payloads": True,
                "supports_sign": False,
                "supports_submit": False,
                "supports_broadcast": False,
                "supports_approve": False,
                "api_success_is_settlement": False,
                "settlement_via": "xrpl",
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    async def fetch_payload(
        self,
        payload_uuid: str,
        *,
        context: OperationContext,
    ) -> XamanPayload:
        """Fetch and normalize a single payload by uuid."""

        context.check_active()
        if self.backend is None:
            raise InvalidRequestError("backend is required for fetch_payload")
        raw = await self.backend.get_payload(payload_uuid, context=context)
        if not raw:
            raise ProviderError(f"empty payload response for {payload_uuid}")
        return parse_xaman_payload(
            raw, network=self.network, privacy=self._privacy
        )

    async def ingest_payloads(
        self,
        *,
        context: OperationContext,
        cursor: str | None = None,
    ) -> AsyncIterator[RecordBatch]:
        """Paginated payload metadata ingest (read-only)."""

        if self.backend is None:
            raise InvalidRequestError("backend is required for ingest_payloads")
        context.check_active()
        pages = 0
        items = 0
        next_cursor = cursor
        while True:
            context.check_active()
            if pages >= context.limits.max_pages:
                raise ProviderError("max_pages exceeded during payload ingest")
            page = await self.backend.list_payloads(
                cursor=next_cursor,
                limit=min(self.page_size, context.limits.max_items - items or self.page_size),
                context=context,
            )
            pages += 1
            raw_items = list(page.get("payloads") or page.get("items") or [])
            records: list[XamanPayload] = []
            response_bytes = 0
            for raw in raw_items:
                if items >= context.limits.max_items:
                    break
                if not isinstance(raw, Mapping):
                    raise ProviderError("payload list item must be a mapping")
                payload = parse_xaman_payload(
                    raw, network=self.network, privacy=self._privacy
                )
                records.append(payload)
                items += 1
                response_bytes += len(
                    json.dumps(dict(raw), default=str, separators=(",", ":")).encode(
                        "utf-8"
                    )
                )
            batch = RecordBatch(
                records=tuple(records),
                next_cursor=page.get("cursor") if page.get("has_more") else None,
                response_bytes=response_bytes,
            )
            batch.enforce(context.limits)
            yield batch
            next_cursor = page.get("cursor")
            if not page.get("has_more") or not next_cursor:
                break
            if items >= context.limits.max_items:
                break


def fixture_backend_from_payloads(
    payloads: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    *,
    list_pages: Sequence[Mapping[str, Any]] | None = None,
) -> MappingPayloadBackend:
    """Build an offline backend from a list or uuid-keyed map of payloads."""

    if isinstance(payloads, Mapping):
        store = {str(k): v for k, v in payloads.items()}
    else:
        store = {}
        for item in payloads:
            if not isinstance(item, Mapping):
                raise InvalidRequestError("fixture payload must be a mapping")
            meta = item.get("meta") if isinstance(item.get("meta"), Mapping) else {}
            uuid = (
                (meta or {}).get("uuid")
                or item.get("uuid")
                or item.get("payload_uuid")
            )
            if not uuid:
                raise InvalidRequestError("fixture payload missing uuid")
            store[str(uuid)] = item
    return MappingPayloadBackend(
        payloads=store,
        list_pages=tuple(list_pages or ()),
    )


def _decode_json_mapping(body: bytes | str | None, *, label: str) -> Mapping[str, Any]:
    if body is None:
        raise ProviderError(f"empty {label} response body")
    if isinstance(body, bytes):
        text = body.decode("utf-8")
    else:
        text = body
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON in {label} response") from exc
    if not isinstance(data, Mapping):
        raise ProviderError(f"{label} response must be a JSON object")
    return data


__all__ = [
    "DEFAULT_API_BASE",
    "HttpPayloadBackend",
    "MappingPayloadBackend",
    "PROVIDER_FAMILY",
    "PROVIDER_NAME",
    "XamanPayloadProvider",
    "XamanResponseBackend",
    "fixture_backend_from_payloads",
]
