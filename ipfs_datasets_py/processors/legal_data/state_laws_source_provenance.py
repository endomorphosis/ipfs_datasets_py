"""Fail-closed verification for official state-law byte transports.

Archival services are transports, not source authorities.  This module keeps
those concepts separate: a caller supplies the cataloged official URL and the
SHA-256 of the bytes it expects, while the receipt proves how those exact
bytes were obtained.  A generic ``archive`` or ``cache`` label is never a
proof.

The receipt shape intentionally follows the transport receipts first used by
the Georgia archived-official corpus.  The verifier is state-neutral so that
scraper and the legacy adapter use the same checks.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit

from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    parse_exact_http_locator,
    parse_wayback_archive_url,
    same_exact_http_locator,
    validate_wayback_cdx_url,
)

_MODULE_SOURCE_PATH = Path(__file__).resolve()
MODULE_IMPORT_SOURCE_SHA256 = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()


def assert_module_source_unchanged() -> str:
    """Fail if this producer's source bytes changed after module import."""

    current = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()
    if current != MODULE_IMPORT_SOURCE_SHA256:
        raise RuntimeError(f"loaded module source drifted on disk: {_MODULE_SOURCE_PATH}")
    return current

_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_ARCHIVE_TIMESTAMP_RE: Final = re.compile(r"^\d{14}$")
ARCHIVE_TRANSPORT_KINDS: Final = frozenset(
    {"wayback", "common_crawl", "common_crawl_insecure_tls", "archive_is"}
)
CACHE_TRANSPORT_KINDS: Final = frozenset(
    {"fetch_cache", "ipfs_page_cache", "durable_cache"}
)
DIRECT_TRANSPORT_KINDS: Final = frozenset({"direct", "browser_rendered"})

_ARCHIVE_IS_HOSTS: Final = frozenset({"archive.is", "archive.ph", "archive.today"})
_COMMON_CRAWL_HOST = "data.commoncrawl.org"
_MAX_CACHE_DEPTH = 8
_WAYBACK_CDX_FIELDS = (
    "urlkey,timestamp,original,mimetype,statuscode,digest,length"
)
_WAYBACK_CDX_QUERY_KEYS: Final = (
    "url",
    "matchType",
    "output",
    "fl",
    "filter",
    "filter",
    "sort",
    "collapse",
    "limit",
)
_WAYBACK_DISCOVERY_FIELDS: Final = (
    "wayback_cdx_query_url",
    "wayback_cdx_response_sha256",
    "wayback_cdx_fetched_at",
)
_COMMON_CRAWL_POINTER_FIELDS: Final = (
    "common_crawl_indexed_url",
    "common_crawl_warc_filename",
    "common_crawl_warc_offset",
    "common_crawl_warc_length",
    "common_crawl_collection",
)


class StateLawTransportReceiptError(ValueError):
    """An official-byte transport receipt is absent, generic, or unbound."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True, slots=True)
class VerifiedStateLawTransport:
    """Canonical proof that a transport yielded exact official-source bytes."""

    official_url: str
    content_sha256: str
    transport_chain: tuple[str, ...]
    archive_url: str | None = None
    archive_timestamp: str | None = None
    wayback_cdx_query_url: str | None = None
    wayback_cdx_response_sha256: str | None = None
    wayback_cdx_fetched_at: str | None = None
    common_crawl_indexed_url: str | None = None
    common_crawl_warc_filename: str | None = None
    common_crawl_warc_offset: int | None = None
    common_crawl_warc_length: int | None = None
    common_crawl_collection: str | None = None

    @property
    def leaf_transport(self) -> str:
        return self.transport_chain[-1]

    @property
    def cache_depth(self) -> int:
        return sum(kind in CACHE_TRANSPORT_KINDS for kind in self.transport_chain)

    @property
    def is_archival(self) -> bool:
        return self.leaf_transport in ARCHIVE_TRANSPORT_KINDS

    def to_dict(self) -> dict[str, Any]:
        value = {
            "archive_timestamp": self.archive_timestamp,
            "archive_url": self.archive_url,
            "cache_depth": self.cache_depth,
            "content_sha256": self.content_sha256,
            "leaf_transport": self.leaf_transport,
            "official_url": self.official_url,
            "transport_chain": list(self.transport_chain),
            "verified": True,
        }
        for field in (*_WAYBACK_DISCOVERY_FIELDS, *_COMMON_CRAWL_POINTER_FIELDS):
            field_value = getattr(self, field)
            if field_value is not None:
                value[field] = field_value
        return value


def _normalize_sha256(value: object, *, field: str) -> str:
    digest = str(value or "").strip().lower().removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(digest):
        raise StateLawTransportReceiptError(
            "invalid_content_sha256",
            f"{field} must be an exact SHA-256 digest",
        )
    return digest


def _normalize_official_url(value: object, *, field: str) -> str:
    try:
        return parse_exact_http_locator(value).raw
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_official_url",
            f"{field} must be a strict unauthenticated default-port HTTP(S) URL",
        ) from exc


def _same_locator(left: str, right: str) -> bool:
    """Compare exact locators while tolerating only a terminal slash."""

    return same_exact_http_locator(left, right)


def _transport_kind(receipt: Mapping[str, Any]) -> str:
    values = {
        str(receipt.get(key) or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        for key in (
            "source_transport",
            "transport_kind",
            "fetch_transport",
            "acquisition_transport",
            "kind",
            "provider",
        )
        if str(receipt.get(key) or "").strip()
    }
    if len(values) > 1:
        raise StateLawTransportReceiptError(
            "conflicting_transport_kinds",
            "transport receipt declares conflicting provider kinds",
        )
    return next(iter(values), "")


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    values = {
        _normalize_sha256(receipt[key], field=f"transport receipt {key}")
        for key in (
            "content_sha256",
            "sha256",
            "body_sha256",
            "raw_sha256",
            "content_digest",
        )
        if receipt.get(key) not in (None, "")
    }
    if len(values) > 1:
        raise StateLawTransportReceiptError(
            "conflicting_content_sha256",
            "transport receipt declares conflicting body digests",
        )
    if not values:
        return _normalize_sha256("", field="transport receipt content digest")
    return next(iter(values))


def _receipt_official_url(receipt: Mapping[str, Any]) -> str:
    values = [
        _normalize_official_url(receipt[key], field=f"transport receipt {key}")
        for key in (
            "official_url",
            "official_source_url",
            "requested_url",
            "source_url",
        )
        if receipt.get(key) not in (None, "")
    ]
    if not values:
        return _normalize_official_url("", field="transport receipt official URL")
    first = values[0]
    if any(not _same_locator(first, value) for value in values[1:]):
        raise StateLawTransportReceiptError(
            "conflicting_official_urls",
            "transport receipt declares conflicting official locators",
        )
    return first


def _exact_archive_timestamp(value: object) -> str:
    raw_stamp = str(value or "")
    stamp = raw_stamp.strip()
    if stamp != raw_stamp:
        raise StateLawTransportReceiptError(
            "invalid_archive_timestamp",
            "archive timestamp must not contain surrounding whitespace",
        )
    if not _ARCHIVE_TIMESTAMP_RE.fullmatch(stamp):
        raise StateLawTransportReceiptError(
            "missing_archive_timestamp",
            "archival transport requires a fourteen-digit UTC snapshot timestamp",
        )
    try:
        datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_archive_timestamp",
            "archive timestamp is not a real calendar time",
        ) from exc
    return stamp


def _wayback_binding(
    archive_url: str,
    official_url: str,
    timestamp: str,
    *,
    allow_plain_retained: bool,
) -> bool:
    try:
        replay = parse_wayback_archive_url(
            archive_url,
            allowed_modifiers=("", "id_") if allow_plain_retained else ("id_",),
            require_identity_modifier=not allow_plain_retained,
        )
    except ValueError:
        return False
    return replay.timestamp == timestamp and _same_locator(
        replay.original_url, official_url
    )


def _strict_archive_url(value: object) -> str:
    try:
        return parse_exact_http_locator(value).raw
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_archive_url",
            "archive locator must be a strict unauthenticated default-port HTTP(S) URL",
        ) from exc


def _field_bundle_present(
    receipt: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    code: str,
) -> bool:
    present = [field for field in fields if field in receipt]
    if not present:
        return False
    if len(present) != len(fields):
        raise StateLawTransportReceiptError(
            code,
            "optional transport evidence must be supplied as one complete bundle",
        )
    return True


def _decode_exact_original_alternatives(filter_value: str) -> tuple[str, ...]:
    """Decode only the literal alternation emitted by the inventory builder."""

    prefix = "original:^(?:"
    suffix = ")$"
    if not filter_value.startswith(prefix) or not filter_value.endswith(suffix):
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_original_filter",
            "Wayback CDX original filter must be an anchored literal alternation",
        )
    encoded = filter_value[len(prefix) : -len(suffix)]
    if not encoded:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_original_filter",
            "Wayback CDX original filter must contain at least one target",
        )
    alternatives: list[str] = []
    literal: list[str] = []
    index = 0
    regex_metacharacters = frozenset(".^$*+?{}[]()|")
    while index < len(encoded):
        character = encoded[index]
        if character == "|":
            if not literal:
                raise StateLawTransportReceiptError(
                    "invalid_wayback_cdx_original_filter",
                    "Wayback CDX original filter contains an empty alternative",
                )
            alternatives.append("".join(literal))
            literal = []
            index += 1
            continue
        if character == "\\":
            index += 1
            if index >= len(encoded):
                raise StateLawTransportReceiptError(
                    "invalid_wayback_cdx_original_filter",
                    "Wayback CDX original filter has a dangling escape",
                )
            literal.append(encoded[index])
            index += 1
            continue
        if character in regex_metacharacters:
            raise StateLawTransportReceiptError(
                "invalid_wayback_cdx_original_filter",
                "Wayback CDX original filter may not contain regex operators",
            )
        literal.append(character)
        index += 1
    if not literal:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_original_filter",
            "Wayback CDX original filter contains an empty alternative",
        )
    alternatives.append("".join(literal))
    if len(set(alternatives)) != len(alternatives):
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_original_filter",
            "Wayback CDX original filter contains duplicate alternatives",
        )
    canonical = "original:^(?:" + "|".join(
        re.escape(value) for value in alternatives
    ) + ")$"
    if canonical != filter_value:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_original_filter",
            "Wayback CDX original filter is not in canonical literal form",
        )
    return tuple(alternatives)


def _validate_wayback_discovery_bundle(
    receipt: Mapping[str, Any],
    *,
    official_url: str,
    kind: str,
    required: bool,
) -> dict[str, Any]:
    present = _field_bundle_present(
        receipt,
        _WAYBACK_DISCOVERY_FIELDS,
        code="incomplete_wayback_cdx_evidence",
    )
    if not present:
        if required:
            raise StateLawTransportReceiptError(
                "missing_wayback_cdx_evidence",
                "strict Wayback evidence requires its complete CDX discovery receipt",
            )
        return {}
    if kind != "wayback":
        raise StateLawTransportReceiptError(
            "wayback_cdx_evidence_transport_mismatch",
            "Wayback CDX evidence may only accompany a Wayback leaf transport",
        )
    try:
        query_url = validate_wayback_cdx_url(
            receipt.get("wayback_cdx_query_url"),
            require_query=True,
        )
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_url",
            "Wayback discovery must use the canonical HTTPS CDX endpoint",
        ) from exc

    try:
        query_pairs = parse_qsl(
            urlsplit(query_url).query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_contract",
            "Wayback CDX query parameters are not well formed",
        ) from exc
    if tuple(key for key, _value in query_pairs) != _WAYBACK_CDX_QUERY_KEYS:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_contract",
            "Wayback CDX query has missing, duplicate, reordered, or extra parameters",
        )
    (
        (_url_key, prefix_value),
        (_match_key, match_type),
        (_output_key, output),
        (_fl_key, field_list),
        (_status_filter_key, status_filter),
        (_original_filter_key, original_filter),
        (_sort_key, sort),
        (_collapse_key, collapse),
        (_limit_key, limit_value),
    ) = query_pairs
    if (
        match_type != "prefix"
        or output != "json"
        or field_list != _WAYBACK_CDX_FIELDS
        or status_filter != "statuscode:200"
        or sort != "reverse"
        or collapse != "urlkey"
        or re.fullmatch(r"[1-9][0-9]*", limit_value) is None
    ):
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_contract",
            "Wayback CDX query does not use the fixed bounded inventory semantics",
        )
    alternatives = _decode_exact_original_alternatives(original_filter)
    if int(limit_value) < len(alternatives):
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_contract",
            "Wayback CDX result limit cannot prove the exact-target row universe",
        )
    expected_query = "https://web.archive.org/cdx/search/cdx?" + urlencode(
        query_pairs,
        doseq=True,
        safe=":/",
    )
    if expected_query != query_url:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_query_contract",
            "Wayback CDX query encoding is not canonical",
        )
    try:
        prefix = parse_exact_http_locator(prefix_value)
        official = parse_exact_http_locator(official_url)
        parsed_alternatives = [
            parse_exact_http_locator(value) for value in alternatives
        ]
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "unbound_wayback_cdx_query",
            "Wayback CDX prefix is not a strict official-source locator",
        ) from exc
    prefix_binds = (
        same_exact_http_locator(prefix.raw, official.raw)
        if prefix.has_query
        else (
            prefix.scheme == official.scheme
            and prefix.hostname == official.hostname
            and official.path.startswith(prefix.path)
        )
    )
    filter_binds = any(
        same_exact_http_locator(candidate.raw, official.raw)
        for candidate in parsed_alternatives
    )
    alternatives_bind_prefix = all(
        (
            same_exact_http_locator(prefix.raw, candidate.raw)
            if prefix.has_query
            else (
                prefix.scheme == candidate.scheme
                and prefix.hostname == candidate.hostname
                and candidate.path.startswith(prefix.path)
            )
        )
        for candidate in parsed_alternatives
    )
    if not prefix_binds or not filter_binds or not alternatives_bind_prefix:
        raise StateLawTransportReceiptError(
            "unbound_wayback_cdx_query",
            "Wayback CDX discovery query does not bind the official target",
        )

    response_sha256 = str(receipt.get("wayback_cdx_response_sha256") or "")
    if _SHA256_RE.fullmatch(response_sha256) is None:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_response_sha256",
            "Wayback CDX response digest must be exact lowercase SHA-256",
        )
    fetched_at_value = str(receipt.get("wayback_cdx_fetched_at") or "")
    if not fetched_at_value or fetched_at_value != fetched_at_value.strip():
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_fetched_at",
            "Wayback CDX fetch time must be an exact timezone-aware ISO timestamp",
        )
    try:
        fetched_at = datetime.fromisoformat(fetched_at_value)
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_fetched_at",
            "Wayback CDX fetch time must use timezone-aware ISO syntax",
        ) from exc
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise StateLawTransportReceiptError(
            "invalid_wayback_cdx_fetched_at",
            "Wayback CDX fetch time must include an offset",
        )
    return {
        "wayback_cdx_query_url": query_url,
        "wayback_cdx_response_sha256": response_sha256,
        "wayback_cdx_fetched_at": fetched_at_value,
    }


def _validate_common_crawl_pointer_bundle(
    receipt: Mapping[str, Any],
    *,
    official_url: str,
    archive_url: str | None,
    kind: str,
    required: bool,
) -> dict[str, Any]:
    present = _field_bundle_present(
        receipt,
        _COMMON_CRAWL_POINTER_FIELDS,
        code="incomplete_common_crawl_pointer",
    )
    if not present:
        if required:
            raise StateLawTransportReceiptError(
                "missing_common_crawl_pointer",
                "strict Common Crawl evidence requires its complete WARC pointer",
            )
        return {}
    if not kind.startswith("common_crawl"):
        raise StateLawTransportReceiptError(
            "common_crawl_pointer_transport_mismatch",
            "Common Crawl pointer evidence may only accompany a Common Crawl leaf transport",
        )
    try:
        indexed_url = parse_exact_http_locator(
            receipt.get("common_crawl_indexed_url")
        ).raw
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "invalid_common_crawl_indexed_url",
            "Common Crawl indexed URL is not a strict HTTP(S) locator",
        ) from exc
    if not same_exact_http_locator(
        indexed_url,
        official_url,
        allow_http_https_equivalence=True,
    ):
        raise StateLawTransportReceiptError(
            "common_crawl_indexed_url_mismatch",
            "Common Crawl indexed URL does not bind the official target",
        )

    filename_value = receipt.get("common_crawl_warc_filename")
    if type(filename_value) is not str:
        raise StateLawTransportReceiptError(
            "invalid_common_crawl_warc_filename",
            "Common Crawl WARC filename must be an exact string",
        )
    filename = filename_value
    parts = filename.split("/")
    if (
        not filename
        or filename != filename.strip()
        or filename.startswith("/")
        or "\\" in filename
        or "%" in filename
        or "?" in filename
        or "#" in filename
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in filename)
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts) < 3
        or parts[0] != "crawl-data"
        or re.fullmatch(r".+\.warc(?:\.gz)?", parts[-1], re.IGNORECASE) is None
    ):
        raise StateLawTransportReceiptError(
            "invalid_common_crawl_warc_filename",
            "Common Crawl WARC filename must be one safe crawl-data object path",
        )
    collection = str(receipt.get("common_crawl_collection") or "")
    if (
        not collection
        or collection != collection.strip()
        or re.fullmatch(r"[A-Za-z0-9._-]+", collection) is None
        or parts[1] != collection
    ):
        raise StateLawTransportReceiptError(
            "common_crawl_collection_mismatch",
            "Common Crawl collection must match the WARC object path",
        )
    offset = receipt.get("common_crawl_warc_offset")
    length = receipt.get("common_crawl_warc_length")
    if type(offset) is not int or offset < 0:
        raise StateLawTransportReceiptError(
            "invalid_common_crawl_warc_offset",
            "Common Crawl WARC offset must be a non-negative integer",
        )
    if type(length) is not int or length <= 0:
        raise StateLawTransportReceiptError(
            "invalid_common_crawl_warc_length",
            "Common Crawl WARC length must be a positive integer",
        )
    try:
        archive = parse_exact_http_locator(archive_url).raw
        parsed_archive = parse_exact_http_locator(archive)
    except ValueError as exc:
        raise StateLawTransportReceiptError(
            "common_crawl_warc_mismatch",
            "Common Crawl pointer lacks a canonical WARC download locator",
        ) from exc
    if (
        parsed_archive.scheme != "https"
        or parsed_archive.hostname != _COMMON_CRAWL_HOST
        or parsed_archive.path != f"/{filename}"
        or parsed_archive.has_query
    ):
        raise StateLawTransportReceiptError(
            "common_crawl_warc_mismatch",
            "Common Crawl archive locator does not bind the exact WARC object",
        )
    return {
        "common_crawl_indexed_url": indexed_url,
        "common_crawl_warc_filename": filename,
        "common_crawl_warc_offset": offset,
        "common_crawl_warc_length": length,
        "common_crawl_collection": collection,
    }


def _verify_one(
    receipt: Mapping[str, Any],
    *,
    official_url: str,
    content_sha256: str,
    depth: int,
    allow_legacy_retained: bool,
) -> VerifiedStateLawTransport:
    if depth > _MAX_CACHE_DEPTH:
        raise StateLawTransportReceiptError(
            "transport_receipt_depth_exceeded",
            "durable-cache origin chain is unexpectedly deep",
        )

    declared_url = _receipt_official_url(receipt)
    if not _same_locator(declared_url, official_url):
        raise StateLawTransportReceiptError(
            "official_url_mismatch",
            "transport receipt does not bind the expected official locator",
        )
    declared_digest = _receipt_digest(receipt)
    if declared_digest != content_sha256:
        raise StateLawTransportReceiptError(
            "content_sha256_mismatch",
            "transport receipt does not bind the expected body bytes",
        )

    kind = _transport_kind(receipt)
    if not kind:
        raise StateLawTransportReceiptError(
            "missing_transport_kind",
            "transport receipt lacks an exact provider kind",
        )
    if kind in CACHE_TRANSPORT_KINDS:
        _validate_wayback_discovery_bundle(
            receipt,
            official_url=official_url,
            kind=kind,
            required=False,
        )
        _validate_common_crawl_pointer_bundle(
            receipt,
            official_url=official_url,
            archive_url=None,
            kind=kind,
            required=False,
        )
        origin = receipt.get("origin_transport_receipt")
        if not isinstance(origin, Mapping):
            raise StateLawTransportReceiptError(
                "missing_origin_transport_receipt",
                "cache transport lacks its original byte-transport receipt",
            )
        verified = _verify_one(
            origin,
            official_url=official_url,
            content_sha256=content_sha256,
            depth=depth + 1,
            allow_legacy_retained=allow_legacy_retained,
        )
        outer_archive_urls = [
            _strict_archive_url(receipt.get(key))
            for key in ("archive_url", "transport_url", "archivedAt")
            if receipt.get(key) not in (None, "")
        ]
        outer_archive_url = outer_archive_urls[0] if outer_archive_urls else ""
        if outer_archive_urls and any(
            not _same_locator(outer_archive_url, value)
            for value in outer_archive_urls[1:]
        ):
            raise StateLawTransportReceiptError(
                "cache_archive_url_mismatch",
                "cache receipt declares conflicting archive locators",
            )
        if outer_archive_url and (
            not verified.archive_url
            or not _same_locator(outer_archive_url, verified.archive_url)
        ):
            raise StateLawTransportReceiptError(
                "cache_archive_url_mismatch",
                "cache receipt conflicts with its origin archive locator",
            )
        outer_timestamp = str(receipt.get("archive_timestamp") or "").strip()
        if outer_timestamp and outer_timestamp != str(verified.archive_timestamp or ""):
            raise StateLawTransportReceiptError(
                "cache_archive_timestamp_mismatch",
                "cache receipt conflicts with its origin archive timestamp",
            )
        return VerifiedStateLawTransport(
            official_url=verified.official_url,
            content_sha256=verified.content_sha256,
            transport_chain=(kind, *verified.transport_chain),
            archive_url=verified.archive_url,
            archive_timestamp=verified.archive_timestamp,
            wayback_cdx_query_url=verified.wayback_cdx_query_url,
            wayback_cdx_response_sha256=verified.wayback_cdx_response_sha256,
            wayback_cdx_fetched_at=verified.wayback_cdx_fetched_at,
            common_crawl_indexed_url=verified.common_crawl_indexed_url,
            common_crawl_warc_filename=verified.common_crawl_warc_filename,
            common_crawl_warc_offset=verified.common_crawl_warc_offset,
            common_crawl_warc_length=verified.common_crawl_warc_length,
            common_crawl_collection=verified.common_crawl_collection,
        )

    if kind in DIRECT_TRANSPORT_KINDS:
        _validate_wayback_discovery_bundle(
            receipt,
            official_url=official_url,
            kind=kind,
            required=False,
        )
        _validate_common_crawl_pointer_bundle(
            receipt,
            official_url=official_url,
            archive_url=None,
            kind=kind,
            required=False,
        )
        if any(
            receipt.get(key) not in (None, "")
            for key in ("archive_url", "transport_url", "archivedAt", "archive_timestamp")
        ):
            raise StateLawTransportReceiptError(
                "direct_transport_has_archive_url",
                "direct transport cannot also claim an archival locator",
            )
        return VerifiedStateLawTransport(
            official_url=official_url,
            content_sha256=content_sha256,
            transport_chain=(kind,),
        )

    if kind not in ARCHIVE_TRANSPORT_KINDS:
        raise StateLawTransportReceiptError(
            "unsupported_transport_kind",
            f"generic or unsupported transport kind {kind!r}",
        )

    archive_urls = [
        _strict_archive_url(receipt.get(key))
        for key in ("archive_url", "transport_url", "archivedAt")
        if str(receipt.get(key) or "").strip()
    ]
    if not archive_urls:
        raise StateLawTransportReceiptError(
            "missing_archive_url",
            "archival transport lacks an immutable archive locator",
        )
    archive_url = archive_urls[0]
    if any(not _same_locator(archive_url, value) for value in archive_urls[1:]):
        raise StateLawTransportReceiptError(
            "conflicting_archive_urls",
            "transport receipt declares conflicting archive locators",
        )
    parsed_archive = parse_exact_http_locator(archive_url)
    archive_host = parsed_archive.hostname
    timestamp = _exact_archive_timestamp(receipt.get("archive_timestamp"))

    if kind == "wayback":
        if not _wayback_binding(
            archive_url,
            official_url,
            timestamp,
            allow_plain_retained=allow_legacy_retained,
        ):
            raise StateLawTransportReceiptError(
                "wayback_official_url_mismatch",
                "Wayback snapshot does not encode the expected official locator and timestamp",
            )
    elif kind.startswith("common_crawl"):
        if (
            parsed_archive.scheme != "https"
            or archive_host != _COMMON_CRAWL_HOST
            or parsed_archive.has_query
            or not re.search(r"\.warc(?:\.gz)?$", parsed_archive.path, re.IGNORECASE)
        ):
            raise StateLawTransportReceiptError(
                "common_crawl_warc_mismatch",
                "Common Crawl receipt is not bound to a data.commoncrawl.org WARC object",
            )
    elif not allow_legacy_retained:
        raise StateLawTransportReceiptError(
            "archive_is_not_authorizing",
            "archive.is is retained migration evidence, not strict publication evidence",
        )
    elif archive_host not in _ARCHIVE_IS_HOSTS:
        raise StateLawTransportReceiptError(
            "archive_is_host_mismatch",
            "archive.is receipt uses an unexpected host",
        )

    discovery = _validate_wayback_discovery_bundle(
        receipt,
        official_url=official_url,
        kind=kind,
        required=(kind == "wayback" and not allow_legacy_retained),
    )
    common_crawl_pointer = _validate_common_crawl_pointer_bundle(
        receipt,
        official_url=official_url,
        archive_url=archive_url,
        kind=kind,
        required=(kind.startswith("common_crawl") and not allow_legacy_retained),
    )

    return VerifiedStateLawTransport(
        official_url=official_url,
        content_sha256=content_sha256,
        transport_chain=(kind,),
        archive_url=archive_url,
        archive_timestamp=timestamp,
        **discovery,
        **common_crawl_pointer,
    )


def verify_state_law_transport_receipt(
    receipt: Mapping[str, Any],
    *,
    official_url: str | None = None,
    content_sha256: str | None = None,
    allow_legacy_retained: bool = False,
) -> VerifiedStateLawTransport:
    """Verify one direct/archive/cache receipt against exact expected bytes.

    ``official_url`` and ``content_sha256`` may be supplied by a caller that
    already has independent evidence.  When omitted, the values are read from
    the receipt so callers can canonicalize a receipt and later match it to a
    row.  That later match remains mandatory for corpus admission.
    """

    if not isinstance(allow_legacy_retained, bool):
        raise TypeError("allow_legacy_retained must be a boolean")
    if not isinstance(receipt, Mapping):
        raise StateLawTransportReceiptError(
            "transport_receipt_not_mapping",
            "transport receipt must be a mapping",
        )
    expected_url = (
        _normalize_official_url(official_url, field="expected official URL")
        if official_url is not None
        else _receipt_official_url(receipt)
    )
    expected_digest = (
        _normalize_sha256(content_sha256, field="expected content SHA-256")
        if content_sha256 is not None
        else _receipt_digest(receipt)
    )
    return _verify_one(
        receipt,
        official_url=expected_url,
        content_sha256=expected_digest,
        depth=0,
        allow_legacy_retained=allow_legacy_retained,
    )


def canonicalize_state_law_transport_receipt(
    receipt: Mapping[str, Any],
    *,
    official_url: str | None = None,
    content_sha256: str | None = None,
    allow_legacy_retained: bool = False,
) -> dict[str, Any]:
    """Return a minimal replayable receipt after full verification.

    Cache layers retain a recursively canonicalized origin receipt.  The
    returned object can therefore be embedded in a normalized row and later
    passed back to :func:`verify_state_law_transport_receipt` without relying
    on scraper-private fields.
    """

    verified = verify_state_law_transport_receipt(
        receipt,
        official_url=official_url,
        content_sha256=content_sha256,
        allow_legacy_retained=allow_legacy_retained,
    )
    canonical: dict[str, Any] = {
        "archive_timestamp": verified.archive_timestamp,
        "archive_url": verified.archive_url,
        "content_sha256": verified.content_sha256,
        "official_url": verified.official_url,
        "source_transport": verified.leaf_transport,
    }
    for field in (*_WAYBACK_DISCOVERY_FIELDS, *_COMMON_CRAWL_POINTER_FIELDS):
        field_value = getattr(verified, field)
        if field_value is not None:
            canonical[field] = field_value
    if not verified.is_archival:
        canonical.pop("archive_timestamp")
        canonical.pop("archive_url")
    for cache_kind in reversed(verified.transport_chain[:-1]):
        canonical = {
            "content_sha256": verified.content_sha256,
            "official_url": verified.official_url,
            "origin_transport_receipt": canonical,
            "source_transport": cache_kind,
        }
    return canonical


__all__ = [
    "ARCHIVE_TRANSPORT_KINDS",
    "CACHE_TRANSPORT_KINDS",
    "DIRECT_TRANSPORT_KINDS",
    "MODULE_IMPORT_SOURCE_SHA256",
    "StateLawTransportReceiptError",
    "VerifiedStateLawTransport",
    "assert_module_source_unchanged",
    "canonicalize_state_law_transport_receipt",
    "verify_state_law_transport_receipt",
]
