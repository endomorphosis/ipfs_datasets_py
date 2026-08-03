"""ODP Patent File Wrapper client (PATLAW-021).

Authenticated, paginated, bounded retrieval against the USPTO Open Data
Portal Patent File Wrapper surface:

* ``GET /api/v1/patent/applications/{applicationNumberText}``
* ``GET /api/v1/patent/applications/{applicationNumberText}/meta-data``
* ``GET /api/v1/patent/applications/{applicationNumberText}/transactions``
* ``GET /api/v1/patent/applications/{applicationNumberText}/documents``
* ``POST /api/v1/patent/applications/search`` (offset/limit pagination)

Contract notes (official docs / swagger 1.0.0):

* Base URL: ``https://api.uspto.gov`` (injectable)
* Auth header: ``X-API-KEY`` (never query-string; never written to receipts)
* Rate limits are **not** hard-coded here; inject :class:`RatePolicy` only when
  the operator has a current authorized value from
  https://data.uspto.gov/apis/api-rate-limits

All status classes (200/401/403/404/429/5xx), pagination, schema drift,
malformed payloads, cancellation, and retry-budget exhaustion produce typed
:class:`ProviderResult` values. Live network I/O is optional; unit tests use
:class:`RecordedHttpTransport` with fixtures under
``tests/fixtures/uspto/odp/http``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import quote

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ApplicationIdentity,
    SourceReceipt,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IdentifierStatus,
    normalize_application_number,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    DEFAULT_ODP_BASE_URL,
    ApiKeySecret,
    CancellationToken,
    CircuitBreaker,
    ConditionalCache,
    HttpTransport,
    PageCheckpoint,
    ProviderConfigError,
    ProviderHttpClient,
    ProviderMalformedError,
    ProviderOutcomeKind,
    ProviderResult,
    ProviderSchemaDriftError,
    ProviderSchemaError,
    RatePolicy,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
    TransportLimits,
    format_utc,
    load_recorded_exchanges,
    sanitize_secret_text,
)

PATENT_FILE_WRAPPER_SCHEMA_VERSION: Final = "uspto.odp.patent_file_wrapper.v1"
PROVIDER_NAME: Final = "odp_patent_file_wrapper"
FIXTURE_SCHEMA_VERSION: Final = "odp-http-fixture-v1"

# Official path templates relative to api.uspto.gov.
PATH_APPLICATION = "/api/v1/patent/applications/{applicationNumberText}"
PATH_META_DATA = "/api/v1/patent/applications/{applicationNumberText}/meta-data"
PATH_TRANSACTIONS = "/api/v1/patent/applications/{applicationNumberText}/transactions"
PATH_DOCUMENTS = "/api/v1/patent/applications/{applicationNumberText}/documents"
PATH_SEARCH = "/api/v1/patent/applications/search"

# Required structural keys for response families (minimal schema gate).
_REQUIRED_APPLICATION_KEYS = frozenset({"count", "patentFileWrapperDataBag"})
_REQUIRED_DOCUMENTS_KEYS = frozenset({"documentBag"})
_REQUIRED_SEARCH_KEYS = frozenset({"count"})

# Known top-level keys; unknown keys trigger schema-drift (additive extras are
# allowed only under patentFileWrapperDataBag bag items, not at the envelope).
_KNOWN_ENVELOPE_KEYS = frozenset(
    {
        "count",
        "patentFileWrapperDataBag",
        "documentBag",
        "facets",
        "requestIdentifier",
        "error",
        "errorDetails",
        "errorDetailed",
        "code",
        "statusCodeBag",
    }
)

PathLike = str | Path
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OdpApplicationSnapshot:
    """Normalized public application / meta-data snapshot from ODP."""

    schema_version: str
    application_number: str
    identity: ApplicationIdentity
    application_meta_data: Mapping[str, Any]
    raw_bag: Mapping[str, Any]
    receipt: SourceReceipt
    event_data: tuple[Mapping[str, Any], ...] = ()
    correspondence_address: tuple[Mapping[str, Any], ...] = ()
    last_ingestion_datetime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_meta_data": dict(self.application_meta_data),
            "application_number": self.application_number,
            "correspondence_address": [dict(x) for x in self.correspondence_address],
            "event_data": [dict(x) for x in self.event_data],
            "identity": self.identity.to_dict(),
            "last_ingestion_datetime": self.last_ingestion_datetime,
            "raw_bag": dict(self.raw_bag),
            "receipt": self.receipt.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class OdpTransactionRecord:
    """One ODP eventDataBag entry (transaction history)."""

    application_number: str
    event: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "event": dict(self.event),
        }


@dataclass(frozen=True, slots=True)
class OdpDocumentRecord:
    """One ODP documentBag entry with download options preserved."""

    application_number: str
    document_identifier: str
    document_code: str | None
    official_date: str | None
    document_code_description: str | None
    direction_category: str | None
    download_options: tuple[Mapping[str, Any], ...]
    raw: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "direction_category": self.direction_category,
            "document_code": self.document_code,
            "document_code_description": self.document_code_description,
            "document_identifier": self.document_identifier,
            "download_options": [dict(x) for x in self.download_options],
            "official_date": self.official_date,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True, slots=True)
class OdpPage:
    """One page of a paginated ODP search (or multi-bag) response."""

    items: tuple[Any, ...]
    offset: int
    limit: int
    total_count: int | None
    next_checkpoint: PageCheckpoint | None
    receipt: SourceReceipt

    @property
    def exhausted(self) -> bool:
        return self.next_checkpoint is None or self.next_checkpoint.exhausted


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderMalformedError(
            f"{name} must be a JSON object", field_name=name
        )
    return value


def validate_odp_envelope(
    payload: Any,
    *,
    required_keys: frozenset[str],
    allow_unknown_envelope_keys: bool = False,
) -> Mapping[str, Any]:
    """Validate a top-level ODP JSON envelope.

    * Missing required keys → :class:`ProviderMalformedError`
    * Unknown top-level keys (when not allowed) → :class:`ProviderSchemaDriftError`
    """

    data = _require_mapping(payload, "payload")
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ProviderMalformedError(
            f"payload missing required key(s): {', '.join(sorted(missing))}",
            field_name=missing[0],
        )
    if not allow_unknown_envelope_keys:
        unknown = sorted(str(k) for k in data.keys() if str(k) not in _KNOWN_ENVELOPE_KEYS)
        if unknown:
            raise ProviderSchemaDriftError(
                f"payload has unexpected top-level key(s): {', '.join(unknown)}",
                field_name=unknown[0],
                code="schema_drift",
            )
    return data


def _first_bag_item(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    bag = payload.get("patentFileWrapperDataBag")
    if bag is None:
        return None
    if not isinstance(bag, Sequence) or isinstance(bag, (str, bytes)):
        raise ProviderMalformedError(
            "patentFileWrapperDataBag must be an array",
            field_name="patentFileWrapperDataBag",
        )
    if not bag:
        return None
    first = bag[0]
    if not isinstance(first, Mapping):
        raise ProviderMalformedError(
            "patentFileWrapperDataBag[0] must be an object",
            field_name="patentFileWrapperDataBag",
        )
    return first


def _as_tuple_of_maps(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProviderMalformedError(
            f"{field_name} must be an array", field_name=field_name
        )
    out: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ProviderMalformedError(
                f"{field_name}[{index}] must be an object",
                field_name=field_name,
            )
        out.append(MappingProxyType(dict(item)))
    return tuple(out)


def normalize_application_number_text(raw: str) -> str:
    """Return compact ODP ``applicationNumberText`` (digits only for US apps)."""

    ident = normalize_application_number(raw, strict=False)
    if ident.status is IdentifierStatus.RESOLVED and ident.compact:
        return ident.compact
    # Allow already-compact PCT / international forms the local normalizer
    # does not own (e.g. PCTUS0719317) when they are non-empty and safe.
    text = str(raw or "").strip().upper().replace("/", "").replace(",", "")
    text = "".join(ch for ch in text if ch.isalnum())
    if not text or len(text) > 32:
        raise ProviderConfigError(
            f"application number is not usable for ODP path: {raw!r}"
        )
    return text


def build_application_identity(application_number: str) -> ApplicationIdentity:
    return ApplicationIdentity(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        application_number=application_number,
        publication_number=None,
        patent_number=None,
        source=PROVIDER_NAME,
        confidence=1.0,
        unresolved_ambiguity=False,
        notes=(),
    )


def parse_application_snapshot(
    payload: Any,
    *,
    receipt: SourceReceipt,
    requested_application_number: str,
) -> OdpApplicationSnapshot:
    data = validate_odp_envelope(payload, required_keys=_REQUIRED_APPLICATION_KEYS)
    bag = _first_bag_item(data)
    if bag is None:
        raise ProviderMalformedError(
            "patentFileWrapperDataBag is empty",
            field_name="patentFileWrapperDataBag",
        )
    app_no = str(
        bag.get("applicationNumberText") or requested_application_number
    ).strip()
    meta = bag.get("applicationMetaData") or {}
    if meta is not None and not isinstance(meta, Mapping):
        raise ProviderMalformedError(
            "applicationMetaData must be an object",
            field_name="applicationMetaData",
        )
    events = _as_tuple_of_maps(bag.get("eventDataBag"), "eventDataBag")
    addresses = _as_tuple_of_maps(
        bag.get("correspondenceAddressBag"), "correspondenceAddressBag"
    )
    last_ingest = bag.get("lastIngestionDateTime")
    if last_ingest is not None:
        last_ingest = str(last_ingest)
    return OdpApplicationSnapshot(
        schema_version=PATENT_FILE_WRAPPER_SCHEMA_VERSION,
        application_number=app_no,
        identity=build_application_identity(app_no),
        application_meta_data=MappingProxyType(dict(meta or {})),
        raw_bag=MappingProxyType(dict(bag)),
        receipt=receipt,
        event_data=events,
        correspondence_address=addresses,
        last_ingestion_datetime=last_ingest,
    )


def parse_transactions(
    payload: Any,
    *,
    requested_application_number: str,
) -> tuple[OdpTransactionRecord, ...]:
    data = validate_odp_envelope(payload, required_keys=_REQUIRED_APPLICATION_KEYS)
    bag = _first_bag_item(data)
    if bag is None:
        return ()
    app_no = str(
        bag.get("applicationNumberText") or requested_application_number
    ).strip()
    events = _as_tuple_of_maps(bag.get("eventDataBag"), "eventDataBag")
    return tuple(
        OdpTransactionRecord(application_number=app_no, event=event) for event in events
    )


def parse_documents(
    payload: Any,
    *,
    requested_application_number: str,
) -> tuple[OdpDocumentRecord, ...]:
    data = validate_odp_envelope(payload, required_keys=_REQUIRED_DOCUMENTS_KEYS)
    docs = data.get("documentBag")
    if not isinstance(docs, Sequence) or isinstance(docs, (str, bytes)):
        raise ProviderMalformedError(
            "documentBag must be an array", field_name="documentBag"
        )
    out: list[OdpDocumentRecord] = []
    for index, item in enumerate(docs):
        if not isinstance(item, Mapping):
            raise ProviderMalformedError(
                f"documentBag[{index}] must be an object",
                field_name="documentBag",
            )
        doc_id = item.get("documentIdentifier")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ProviderMalformedError(
                f"documentBag[{index}].documentIdentifier is required",
                field_name="documentIdentifier",
            )
        downloads = _as_tuple_of_maps(
            item.get("downloadOptionBag"), "downloadOptionBag"
        )
        app_no = str(
            item.get("applicationNumberText") or requested_application_number
        ).strip()
        out.append(
            OdpDocumentRecord(
                application_number=app_no,
                document_identifier=doc_id.strip(),
                document_code=_optional_str(item.get("documentCode")),
                official_date=_optional_str(item.get("officialDate")),
                document_code_description=_optional_str(
                    item.get("documentCodeDescriptionText")
                ),
                direction_category=_optional_str(
                    item.get("documentDirectionCategory")
                ),
                download_options=downloads,
                raw=MappingProxyType(dict(item)),
            )
        )
    return tuple(out)


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _encode_application_number(application_number: str) -> str:
    # Path-safe encoding for PCT forms with residual special characters.
    return quote(application_number, safe="")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class PatentFileWrapperClient:
    """Public ODP Patent File Wrapper provider.

    Construct with an injected transport (recorded fixtures or live HTTP).
    Endpoint, API key, retry policy, and optional rate policy are all
    injected — never read from process environment inside this class.
    """

    _http: ProviderHttpClient
    _default_page_limit: int = 25

    def __init__(
        self,
        transport: HttpTransport,
        *,
        base_url: str = DEFAULT_ODP_BASE_URL,
        api_key: ApiKeySecret | str | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_policy: RatePolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        limits: TransportLimits | None = None,
        cache: ConditionalCache | None = None,
        cancellation: CancellationToken | None = None,
        default_page_limit: int = 25,
        sleep: Callable[[float], None] | None = None,
        wall_clock: Callable[[], Any] | None = None,
        random_sample: Callable[[], float] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "transport": transport,
            "base_url": base_url,
            "api_key": api_key,
            "retry_policy": retry_policy,
            "rate_policy": rate_policy,
            "circuit_breaker": circuit_breaker,
            "limits": limits,
            "cache": cache,
            "cancellation": cancellation,
        }
        if sleep is not None:
            kwargs["sleep"] = sleep
        if wall_clock is not None:
            kwargs["wall_clock"] = wall_clock
        if random_sample is not None:
            kwargs["random_sample"] = random_sample
        self._http = ProviderHttpClient(**kwargs)
        if (
            isinstance(default_page_limit, bool)
            or not isinstance(default_page_limit, int)
            or default_page_limit <= 0
        ):
            raise ProviderConfigError("default_page_limit must be a positive integer")
        self._default_page_limit = default_page_limit

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_recorded_recipe(
        cls,
        recipe: JsonMapping | PathLike,
        *,
        api_key: ApiKeySecret | str | None = "test-key-not-a-secret",
        **kwargs: Any,
    ) -> "PatentFileWrapperClient":
        """Build a client that replays a compact fixture recipe."""

        payload = _load_recipe(recipe)
        transport = RecordedHttpTransport(load_recorded_exchanges(payload))
        return cls(transport, api_key=api_key, **kwargs)

    @classmethod
    def from_fixture_dir(
        cls,
        fixture_dir: PathLike | None = None,
        *,
        recipe_name: str = "odp_http_recipe.json",
        **kwargs: Any,
    ) -> "PatentFileWrapperClient":
        directory = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        return cls.from_recorded_recipe(directory / recipe_name, **kwargs)

    def safe_config(self) -> dict[str, Any]:
        cfg = self._http.safe_config()
        cfg["provider"] = PROVIDER_NAME
        cfg["schema_version"] = PATENT_FILE_WRAPPER_SCHEMA_VERSION
        cfg["default_page_limit"] = self._default_page_limit
        return cfg

    # ------------------------------------------------------------------
    # Application data
    # ------------------------------------------------------------------

    def get_application_data(
        self,
        application_number: str,
        *,
        enable_conditional_cache: bool = True,
    ) -> ProviderResult:
        """Fetch patent application bag (status, meta, optional events)."""

        app_no = normalize_application_number_text(application_number)
        path = PATH_APPLICATION.format(
            applicationNumberText=_encode_application_number(app_no)
        )
        result = self._http.request(
            "GET",
            path,
            enable_conditional_cache=enable_conditional_cache,
            upstream_id=app_no,
            metadata={"resource": "application_data", "application_number": app_no},
        )
        return self._annotate_success_payload(
            result,
            parser=lambda payload, receipt: parse_application_snapshot(
                payload, receipt=receipt, requested_application_number=app_no
            ),
        )

    def get_meta_data(self, application_number: str) -> ProviderResult:
        app_no = normalize_application_number_text(application_number)
        path = PATH_META_DATA.format(
            applicationNumberText=_encode_application_number(app_no)
        )
        result = self._http.request(
            "GET",
            path,
            upstream_id=app_no,
            metadata={"resource": "meta_data", "application_number": app_no},
        )
        return self._annotate_success_payload(
            result,
            parser=lambda payload, receipt: parse_application_snapshot(
                payload, receipt=receipt, requested_application_number=app_no
            ),
        )

    def get_transactions(self, application_number: str) -> ProviderResult:
        app_no = normalize_application_number_text(application_number)
        path = PATH_TRANSACTIONS.format(
            applicationNumberText=_encode_application_number(app_no)
        )
        result = self._http.request(
            "GET",
            path,
            upstream_id=app_no,
            metadata={"resource": "transactions", "application_number": app_no},
        )
        return self._annotate_success_payload(
            result,
            parser=lambda payload, receipt: parse_transactions(
                payload, requested_application_number=app_no
            ),
        )

    def get_documents(
        self,
        application_number: str,
        *,
        document_codes: str | Sequence[str] | None = None,
        official_date_from: str | None = None,
        official_date_to: str | None = None,
    ) -> ProviderResult:
        app_no = normalize_application_number_text(application_number)
        path = PATH_DOCUMENTS.format(
            applicationNumberText=_encode_application_number(app_no)
        )
        query: dict[str, Any] = {}
        if document_codes is not None:
            if isinstance(document_codes, str):
                query["documentCodes"] = document_codes
            else:
                query["documentCodes"] = ",".join(str(c) for c in document_codes)
        if official_date_from:
            query["officialDateFrom"] = official_date_from
        if official_date_to:
            query["officialDateTo"] = official_date_to
        result = self._http.request(
            "GET",
            path,
            query=query or None,
            upstream_id=app_no,
            metadata={"resource": "documents", "application_number": app_no},
        )
        return self._annotate_success_payload(
            result,
            parser=lambda payload, receipt: parse_documents(
                payload, requested_application_number=app_no
            ),
        )

    # ------------------------------------------------------------------
    # Search pagination
    # ------------------------------------------------------------------

    def search(
        self,
        query: str | Mapping[str, Any],
        *,
        offset: int = 0,
        limit: int | None = None,
        checkpoint: PageCheckpoint | None = None,
    ) -> ProviderResult:
        """POST search with offset/limit; returns page + next checkpoint."""

        page_limit = limit if limit is not None else self._default_page_limit
        if checkpoint is not None:
            if checkpoint.resource != "search":
                raise ProviderConfigError(
                    "checkpoint.resource must be 'search' for search()"
                )
            offset = checkpoint.offset
            if checkpoint.limit is not None:
                page_limit = checkpoint.limit
            if checkpoint.exhausted:
                empty_receipt = result_receipt_stub(
                    endpoint=self._http.build_url(PATH_SEARCH),
                    application_number=None,
                )
                return ProviderResult(
                    kind=ProviderOutcomeKind.SUCCESS,
                    status_code=200,
                    receipt=empty_receipt,
                    payload=OdpPage(
                        items=(),
                        offset=offset,
                        limit=page_limit,
                        total_count=0,
                        next_checkpoint=checkpoint,
                        receipt=empty_receipt,
                    ),
                    checkpoint=checkpoint,
                    metadata={"resource": "search", "exhausted": "true"},
                )

        if isinstance(query, Mapping):
            body: dict[str, Any] = dict(query)
        else:
            body = {"q": str(query)}
        body.setdefault(
            "pagination",
            {"offset": int(offset), "limit": int(page_limit)},
        )
        # Prefer explicit top-level pagination when fixture/search expects it.
        if "offset" not in body:
            body["offset"] = int(offset)
        if "limit" not in body:
            body["limit"] = int(page_limit)

        result = self._http.request(
            "POST",
            PATH_SEARCH,
            json_body=body,
            enable_conditional_cache=False,
            metadata={
                "resource": "search",
                "offset": str(offset),
                "limit": str(page_limit),
            },
        )
        if not result.ok:
            return result
        try:
            page = self._parse_search_page(
                result.payload,
                receipt=result.receipt,  # type: ignore[arg-type]
                offset=int(offset),
                limit=int(page_limit),
            )
        except (ProviderSchemaError, ProviderMalformedError, ProviderSchemaDriftError) as exc:
            return _schema_result(result, exc)
        return ProviderResult(
            kind=ProviderOutcomeKind.SUCCESS,
            status_code=result.status_code,
            receipt=result.receipt,
            payload=page,
            checkpoint=page.next_checkpoint,
            cache_hit=result.cache_hit,
            metadata=result.metadata,
        )

    def iter_search_pages(
        self,
        query: str | Mapping[str, Any],
        *,
        limit: int | None = None,
        checkpoint: PageCheckpoint | None = None,
        max_pages: int | None = None,
    ) -> Iterator[ProviderResult]:
        """Yield typed page results until exhausted, cancelled, or capped."""

        page_limit = limit if limit is not None else self._default_page_limit
        max_pages = (
            max_pages
            if max_pages is not None
            else self._http._limits.max_pages  # noqa: SLF001 — intentional bound
        )
        current = checkpoint
        pages = 0
        while pages < max_pages:
            result = self.search(query, limit=page_limit, checkpoint=current)
            yield result
            pages += 1
            if not result.ok:
                return
            page = result.payload
            if not isinstance(page, OdpPage):
                return
            if page.exhausted or page.next_checkpoint is None:
                return
            current = page.next_checkpoint

    def _parse_search_page(
        self,
        payload: Any,
        *,
        receipt: SourceReceipt,
        offset: int,
        limit: int,
    ) -> OdpPage:
        data = validate_odp_envelope(payload, required_keys=_REQUIRED_SEARCH_KEYS)
        total = data.get("count")
        if total is not None and (
            isinstance(total, bool) or not isinstance(total, int) or total < 0
        ):
            raise ProviderMalformedError(
                "count must be a non-negative integer", field_name="count"
            )
        bag = data.get("patentFileWrapperDataBag") or data.get("results") or []
        if not isinstance(bag, Sequence) or isinstance(bag, (str, bytes)):
            raise ProviderMalformedError(
                "search results bag must be an array",
                field_name="patentFileWrapperDataBag",
            )
        items = tuple(bag)
        next_offset = offset + len(items)
        exhausted = len(items) == 0 or (
            total is not None and next_offset >= int(total)
        ) or len(items) < limit
        next_cp = PageCheckpoint(
            resource="search",
            offset=next_offset,
            limit=limit,
            pages_completed=1,
            items_completed=len(items),
            exhausted=exhausted,
            metadata={"total_count": str(total) if total is not None else ""},
        )
        return OdpPage(
            items=items,
            offset=offset,
            limit=limit,
            total_count=None if total is None else int(total),
            next_checkpoint=next_cp,
            receipt=receipt,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _annotate_success_payload(
        self,
        result: ProviderResult,
        *,
        parser: Callable[[Any, SourceReceipt], Any],
    ) -> ProviderResult:
        if not result.ok:
            return result
        if result.receipt is None:
            return ProviderResult(
                kind=ProviderOutcomeKind.MALFORMED,
                status_code=result.status_code,
                receipt=result.receipt,
                error_code="missing_receipt",
                message="success response missing source receipt",
                metadata=result.metadata,
            )
        try:
            parsed = parser(result.payload, result.receipt)
        except ProviderSchemaDriftError as exc:
            return _schema_result(result, exc, kind=ProviderOutcomeKind.SCHEMA_DRIFT)
        except (ProviderSchemaError, ProviderMalformedError) as exc:
            return _schema_result(result, exc, kind=ProviderOutcomeKind.MALFORMED)
        return ProviderResult(
            kind=ProviderOutcomeKind.SUCCESS
            if result.kind is not ProviderOutcomeKind.NOT_MODIFIED
            else ProviderOutcomeKind.NOT_MODIFIED,
            status_code=result.status_code,
            receipt=result.receipt,
            payload=parsed,
            cache_hit=result.cache_hit,
            metadata=result.metadata,
        )


def _schema_result(
    result: ProviderResult,
    exc: Exception,
    *,
    kind: ProviderOutcomeKind | None = None,
) -> ProviderResult:
    if kind is None:
        if isinstance(exc, ProviderSchemaDriftError):
            kind = ProviderOutcomeKind.SCHEMA_DRIFT
        else:
            kind = ProviderOutcomeKind.MALFORMED
    code = getattr(exc, "code", kind.value)
    return ProviderResult(
        kind=kind,
        status_code=result.status_code,
        receipt=result.receipt,
        payload=result.payload,
        error_code=str(code),
        message=sanitize_secret_text(str(exc)),
        cache_hit=result.cache_hit,
        metadata=result.metadata,
    )


def result_receipt_stub(
    *,
    endpoint: str,
    application_number: str | None,
) -> SourceReceipt:
    from ipfs_datasets_py.processors.domains.uspto.providers.base import (
        build_source_receipt,
        HttpRequest,
    )

    request = HttpRequest(method="GET", url=endpoint, headers={})
    return build_source_receipt(
        endpoint=endpoint,
        status_code=200,
        request=request,
        response_body=b"{}",
        upstream_id=application_number,
        cache_hit=True,
        retry_count=0,
        retrieval_utc=format_utc(),
        metadata={"resource": "search", "synthetic": "true"},
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    here = Path(__file__).resolve()
    # providers/ -> uspto/ -> domains/ -> processors/ -> ipfs_datasets_py/ -> repo
    candidates = [
        here.parents[5] / "tests" / "fixtures" / "uspto" / "odp" / "http",
        Path.cwd() / "tests" / "fixtures" / "uspto" / "odp" / "http",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def _load_recipe(recipe: JsonMapping | PathLike) -> dict[str, Any]:
    if isinstance(recipe, Mapping):
        payload = dict(recipe)
    else:
        path = Path(recipe)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ProviderSchemaError(
                f"fixture root must be a mapping: {path}", field_name="root"
            )
        payload = dict(payload)
    schema = payload.get("schema_version")
    if schema and str(schema) not in {
        FIXTURE_SCHEMA_VERSION,
        PATENT_FILE_WRAPPER_SCHEMA_VERSION,
    }:
        if not str(schema).startswith("odp"):
            raise ProviderSchemaError(
                f"unsupported fixture schema_version {schema!r}",
                field_name="schema_version",
            )
    return payload


def build_fixture_recipe(
    exchanges: Sequence[RecordedExchange | Mapping[str, Any]],
    *,
    sequences: Sequence[Mapping[str, Any]] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a compact recipe dict (prefer over bulk golden dumps)."""

    serialized: list[dict[str, Any]] = []
    for item in exchanges:
        if isinstance(item, RecordedExchange):
            serialized.append(
                {
                    "method": item.method,
                    "path": item.path,
                    "status": item.status,
                    "body": item.body,
                    "headers": dict(item.headers or {}),
                    "query": None if item.query is None else dict(item.query),
                }
            )
        else:
            serialized.append(dict(item))
    recipe: dict[str, Any] = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "provider": PROVIDER_NAME,
        "exchanges": serialized,
    }
    if sequences:
        recipe["sequences"] = [dict(s) for s in sequences]
    if notes:
        recipe["notes"] = notes
    return recipe


# Alias matching the plan / AST query name.
OdpPatentFileWrapperClient = PatentFileWrapperClient


__all__ = [
    "FIXTURE_SCHEMA_VERSION",
    "OdpApplicationSnapshot",
    "OdpDocumentRecord",
    "OdpPage",
    "OdpPatentFileWrapperClient",
    "OdpTransactionRecord",
    "PATH_APPLICATION",
    "PATH_DOCUMENTS",
    "PATH_META_DATA",
    "PATH_SEARCH",
    "PATH_TRANSACTIONS",
    "PATENT_FILE_WRAPPER_SCHEMA_VERSION",
    "PROVIDER_NAME",
    "PatentFileWrapperClient",
    "build_application_identity",
    "build_fixture_recipe",
    "default_fixture_dir",
    "normalize_application_number_text",
    "parse_application_snapshot",
    "parse_documents",
    "parse_transactions",
    "validate_odp_envelope",
]
