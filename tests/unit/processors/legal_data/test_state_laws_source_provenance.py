"""Focused checks for fail-closed state-law byte-transport receipts."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
    StateLawTransportReceiptError,
    canonicalize_state_law_transport_receipt,
    verify_state_law_transport_receipt,
)
from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    _wayback_inventory_query_url,
)

OFFICIAL_URL = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
SNAPSHOT = "20260102030405"
BODY_SHA256 = hashlib.sha256(b"retained official statute response bytes").hexdigest()
WAYBACK_URL = f"https://web.archive.org/web/{SNAPSHOT}id_/{OFFICIAL_URL}"
CC_COLLECTION = "CC-MAIN-2026-30"
CC_FILENAME = (
    f"crawl-data/{CC_COLLECTION}/segments/1720000000000.0/warc/example.warc.gz"
)
CC_ARCHIVE_URL = f"https://data.commoncrawl.org/{CC_FILENAME}"


class _FilenameStringifier:
    def __str__(self) -> str:
        return CC_FILENAME


class _IntegerSubclass(int):
    pass


def _wayback_discovery_fields(url: str = OFFICIAL_URL) -> dict[str, object]:
    query, _variant_count = _wayback_inventory_query_url(
        url,
        limit=100,
        exact_originals=[url],
    )
    return {
        "wayback_cdx_query_url": query,
        "wayback_cdx_response_sha256": "a" * 64,
        "wayback_cdx_fetched_at": "2026-08-25T00:00:00+00:00",
    }


def _common_crawl_receipt(**changes: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "archive_timestamp": SNAPSHOT,
        "archive_url": CC_ARCHIVE_URL,
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "source_transport": "common_crawl",
        "common_crawl_indexed_url": OFFICIAL_URL,
        "common_crawl_warc_filename": CC_FILENAME,
        "common_crawl_warc_offset": 1234,
        "common_crawl_warc_length": 567,
        "common_crawl_collection": CC_COLLECTION,
    }
    receipt.update(changes)
    return receipt


def _wayback_receipt(**changes: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "archive_timestamp": SNAPSHOT,
        "archive_url": WAYBACK_URL,
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "source_transport": "wayback",
        **_wayback_discovery_fields(),
    }
    receipt.update(changes)
    return receipt


def test_wayback_receipt_binds_exact_official_locator_timestamp_and_bytes() -> None:
    verified = verify_state_law_transport_receipt(
        _wayback_receipt(),
        official_url=OFFICIAL_URL,
        content_sha256=BODY_SHA256,
    )

    assert verified.official_url == OFFICIAL_URL
    assert verified.content_sha256 == BODY_SHA256
    assert verified.transport_chain == ("wayback",)
    assert verified.archive_url == WAYBACK_URL
    assert verified.archive_timestamp == SNAPSHOT
    assert verified.is_archival is True


@pytest.mark.parametrize(
    ("source_transport", "archive_url"),
    [
        (
            "common_crawl",
            (
                "https://data.commoncrawl.org/crawl-data/CC-MAIN-2026-30/segments/"
                "1720000000000.0/warc/example.warc.gz"
            ),
        ),
        ("archive_is", "https://archive.is/AbCdE"),
    ],
)
def test_other_web_archiving_providers_require_explicit_immutable_receipts(
    source_transport: str,
    archive_url: str,
) -> None:
    receipt = {
        "archive_timestamp": SNAPSHOT,
        "archive_url": archive_url,
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "source_transport": source_transport,
    }
    if source_transport == "common_crawl":
        receipt = _common_crawl_receipt()
    verified = verify_state_law_transport_receipt(
        receipt,
        allow_legacy_retained=source_transport == "archive_is",
    )

    assert verified.leaf_transport == source_transport
    assert verified.archive_url == archive_url


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (
            {
                "archive_url": (
                    f"https://web.archive.org/web/{SNAPSHOT}id_/"
                    "https://docs.legis.wisconsin.gov/document/statutes/9.99"
                )
            },
            "wayback_official_url_mismatch",
        ),
        ({"content_sha256": "0" * 64}, "content_sha256_mismatch"),
        ({"body_sha256": "1" * 64}, "conflicting_content_sha256"),
        ({"transport_kind": "common_crawl"}, "conflicting_transport_kinds"),
        (
            {
                "source_url": (
                    "https://docs.legis.wisconsin.gov/document/statutes/9.99"
                )
            },
            "conflicting_official_urls",
        ),
        ({"source_transport": "archived_https"}, "unsupported_transport_kind"),
        ({"archive_timestamp": "20261399030405"}, "invalid_archive_timestamp"),
    ],
)
def test_unbound_or_generic_archive_receipts_fail_closed(
    changes: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(
            _wayback_receipt(**changes),
            official_url=OFFICIAL_URL,
            content_sha256=BODY_SHA256,
        )

    assert exc_info.value.code == code


def test_durable_cache_requires_and_preserves_verified_origin_receipt() -> None:
    cached = {
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "origin_transport_receipt": _wayback_receipt(),
        "source_transport": "durable_cache",
    }

    verified = verify_state_law_transport_receipt(cached)

    assert verified.transport_chain == ("durable_cache", "wayback")
    assert verified.cache_depth == 1
    assert verified.archive_url == WAYBACK_URL

    canonical = canonicalize_state_law_transport_receipt(cached)
    replayed = verify_state_law_transport_receipt(canonical)
    assert replayed == verified
    assert canonical["origin_transport_receipt"]["source_transport"] == "wayback"

    cached.pop("origin_transport_receipt")
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(cached)
    assert exc_info.value.code == "missing_origin_transport_receipt"


def test_browser_rendered_receipt_is_an_exact_non_archival_transport() -> None:
    verified = verify_state_law_transport_receipt(
        {
            "content_sha256": BODY_SHA256,
            "official_url": OFFICIAL_URL,
            "source_transport": "browser_rendered",
        }
    )

    assert verified.transport_chain == ("browser_rendered",)
    assert verified.is_archival is False
    assert canonicalize_state_law_transport_receipt(
        {
            "content_sha256": BODY_SHA256,
            "official_url": OFFICIAL_URL,
            "source_transport": "browser_rendered",
        }
    ) == {
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "source_transport": "browser_rendered",
    }


def test_retained_plain_wayback_locator_remains_admissible() -> None:
    plain = f"https://web.archive.org/web/{SNAPSHOT}/{OFFICIAL_URL}"
    verified = verify_state_law_transport_receipt(
        _wayback_receipt(archive_url=plain),
        allow_legacy_retained=True,
    )

    assert verified.archive_url == plain


def test_default_port_and_one_terminal_path_slash_normalize_before_query_only() -> None:
    official = "https://example.gov/code/section?q=/"
    receipt_official = "https://example.gov:443/code/section/?q=/"
    archive = f"https://web.archive.org/web/{SNAPSHOT}id_/{receipt_official}"
    verified = verify_state_law_transport_receipt(
        {
            "archive_timestamp": SNAPSHOT,
            "archive_url": archive,
            "content_sha256": BODY_SHA256,
            "official_url": receipt_official,
            "source_transport": "wayback",
            **_wayback_discovery_fields(receipt_official),
        },
        official_url=official,
    )

    assert verified.archive_url == archive


@pytest.mark.parametrize(
    "archive_url",
    [
        f"http://web.archive.org/web/{SNAPSHOT}id_/{OFFICIAL_URL}",
        f"https://www.web.archive.org/web/{SNAPSHOT}id_/{OFFICIAL_URL}",
        f"https://web.archive.org:443/web/{SNAPSHOT}id_/{OFFICIAL_URL}",
        f"https://user@web.archive.org/web/{SNAPSHOT}id_/{OFFICIAL_URL}",
        f"https://web.archive.org/prefix/web/{SNAPSHOT}id_/{OFFICIAL_URL}",
        f"https://web.archive.org/web/{SNAPSHOT}if_/{OFFICIAL_URL}",
        f"https://web.archive.org/web/{SNAPSHOT}id_/{OFFICIAL_URL}#",
    ],
)
def test_wayback_outer_locator_aliases_fail_closed(archive_url: str) -> None:
    with pytest.raises(StateLawTransportReceiptError):
        verify_state_law_transport_receipt(
            _wayback_receipt(archive_url=archive_url)
        )


@pytest.mark.parametrize(
    ("official", "embedded"),
    [
        (
            "https://example.gov/code?a=1&b=2",
            "https://example.gov/code?a=2&b=1",
        ),
        ("https://example.gov/code?a=%20", "https://example.gov/code?a=1+2"),
        ("https://example.gov/code?a=%2F", "https://example.gov/code?a=%2f"),
        ("https://example.gov/code?a=", "https://example.gov/code?a=/"),
        ("https://example.gov/code?a=1", "https://example.gov/code//?a=1"),
    ],
)
def test_wayback_embedded_query_path_and_percent_aliases_fail_closed(
    official: str,
    embedded: str,
) -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(
            {
                "archive_timestamp": SNAPSHOT,
                "archive_url": f"https://web.archive.org/web/{SNAPSHOT}id_/{embedded}",
                "content_sha256": BODY_SHA256,
                "official_url": official,
                "source_transport": "wayback",
            }
        )
    assert exc_info.value.code in {
        "wayback_official_url_mismatch",
        "invalid_archive_url",
    }


def test_wayback_discovery_bundle_is_preserved_and_cache_replayable() -> None:
    leaf = _wayback_receipt(**_wayback_discovery_fields())
    cached = {
        "content_sha256": BODY_SHA256,
        "official_url": OFFICIAL_URL,
        "origin_transport_receipt": leaf,
        "source_transport": "durable_cache",
    }

    canonical = canonicalize_state_law_transport_receipt(cached)
    canonical_leaf = canonical["origin_transport_receipt"]
    for key, value in _wayback_discovery_fields().items():
        assert canonical_leaf[key] == value
    assert verify_state_law_transport_receipt(canonical) == verify_state_law_transport_receipt(cached)


@pytest.mark.parametrize("missing", list(_wayback_discovery_fields()))
def test_wayback_discovery_bundle_is_atomic(missing: str) -> None:
    receipt = _wayback_receipt()
    receipt.pop(missing)
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(receipt)
    assert exc_info.value.code == "incomplete_wayback_cdx_evidence"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (
            {"wayback_cdx_query_url": "http://web.archive.org/cdx/search/cdx?url=x"},
            "invalid_wayback_cdx_query_url",
        ),
        (
            {
                "wayback_cdx_query_url": (
                    "https://web.archive.org/cdx/search/cdx?"
                    "url=https://example.gov/other&filter=original%3A%5Eother%24"
                )
            },
            "invalid_wayback_cdx_query_contract",
        ),
        ({"wayback_cdx_response_sha256": "0"}, "invalid_wayback_cdx_response_sha256"),
        ({"wayback_cdx_fetched_at": "2026-08-25T00:00:00"}, "invalid_wayback_cdx_fetched_at"),
    ],
)
def test_wayback_discovery_fields_fail_closed(
    changes: dict[str, object],
    code: str,
) -> None:
    fields = _wayback_discovery_fields()
    fields.update(changes)
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(_wayback_receipt(**fields))
    assert exc_info.value.code == code


@pytest.mark.parametrize(
    "mutation",
    [
        "regex_widened",
        "extra_parameter",
        "duplicate_output",
        "missing_sort",
        "wrong_match_type",
        "wrong_field_list",
        "widened_status",
        "wrong_sort",
        "wrong_collapse",
        "noncanonical_limit",
        "reordered_parameters",
    ],
)
def test_wayback_cdx_query_contract_rejects_every_semantic_widening(
    mutation: str,
) -> None:
    fields = _wayback_discovery_fields()
    query_url = str(fields["wayback_cdx_query_url"])
    pairs = parse_qsl(urlsplit(query_url).query, keep_blank_values=True)
    if mutation == "regex_widened":
        pairs = [
            (key, "original:.*" if key == "filter" and value.startswith("original:") else value)
            for key, value in pairs
        ]
    elif mutation == "extra_parameter":
        pairs.append(("from", "1900"))
    elif mutation == "duplicate_output":
        pairs.insert(3, ("output", "json"))
    elif mutation == "missing_sort":
        pairs = [(key, value) for key, value in pairs if key != "sort"]
    elif mutation == "wrong_match_type":
        pairs = [(key, "domain" if key == "matchType" else value) for key, value in pairs]
    elif mutation == "wrong_field_list":
        pairs = [(key, "original,timestamp" if key == "fl" else value) for key, value in pairs]
    elif mutation == "widened_status":
        pairs = [
            (key, "statuscode:2.." if key == "filter" and value == "statuscode:200" else value)
            for key, value in pairs
        ]
    elif mutation == "wrong_sort":
        pairs = [(key, "ascending" if key == "sort" else value) for key, value in pairs]
    elif mutation == "wrong_collapse":
        pairs = [(key, "timestamp:8" if key == "collapse" else value) for key, value in pairs]
    elif mutation == "noncanonical_limit":
        pairs = [(key, "0100" if key == "limit" else value) for key, value in pairs]
    else:
        pairs[0], pairs[1] = pairs[1], pairs[0]
    fields["wayback_cdx_query_url"] = (
        "https://web.archive.org/cdx/search/cdx?"
        + urlencode(pairs, doseq=True, safe=":/")
    )

    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(_wayback_receipt(**fields))

    assert exc_info.value.code in {
        "invalid_wayback_cdx_original_filter",
        "invalid_wayback_cdx_query_contract",
    }


def test_strict_default_isolates_retained_wayback_and_common_crawl_compatibility() -> None:
    id_without_discovery = _wayback_receipt()
    for field in _wayback_discovery_fields():
        id_without_discovery.pop(field)
    with pytest.raises(StateLawTransportReceiptError) as wayback_error:
        verify_state_law_transport_receipt(id_without_discovery)
    assert wayback_error.value.code == "missing_wayback_cdx_evidence"
    assert verify_state_law_transport_receipt(
        id_without_discovery,
        allow_legacy_retained=True,
    ).leaf_transport == "wayback"

    common_crawl_without_pointer = {
        key: value
        for key, value in _common_crawl_receipt().items()
        if not key.startswith("common_crawl_")
    }
    with pytest.raises(StateLawTransportReceiptError) as crawl_error:
        verify_state_law_transport_receipt(common_crawl_without_pointer)
    assert crawl_error.value.code == "missing_common_crawl_pointer"
    assert verify_state_law_transport_receipt(
        common_crawl_without_pointer,
        allow_legacy_retained=True,
    ).leaf_transport == "common_crawl"


def test_common_crawl_label_can_never_authorize_a_wayback_locator() -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(
            _common_crawl_receipt(archive_url=WAYBACK_URL)
        )
    assert exc_info.value.code == "common_crawl_warc_mismatch"


def test_common_crawl_pointer_bundle_is_preserved_exactly() -> None:
    source = _common_crawl_receipt()
    canonical = canonicalize_state_law_transport_receipt(source)

    for field in (
        "common_crawl_indexed_url",
        "common_crawl_warc_filename",
        "common_crawl_warc_offset",
        "common_crawl_warc_length",
        "common_crawl_collection",
    ):
        assert canonical[field] == source[field]
    assert verify_state_law_transport_receipt(canonical).common_crawl_warc_offset == 1234


@pytest.mark.parametrize(
    "missing",
    [
        "common_crawl_indexed_url",
        "common_crawl_warc_filename",
        "common_crawl_warc_offset",
        "common_crawl_warc_length",
        "common_crawl_collection",
    ],
)
def test_common_crawl_pointer_bundle_is_atomic(missing: str) -> None:
    receipt = _common_crawl_receipt()
    receipt.pop(missing)
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(receipt)
    assert exc_info.value.code == "incomplete_common_crawl_pointer"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (
            {"common_crawl_indexed_url": OFFICIAL_URL + "?page=/"},
            "common_crawl_indexed_url_mismatch",
        ),
        (
            {"common_crawl_indexed_url": OFFICIAL_URL + "#"},
            "invalid_common_crawl_indexed_url",
        ),
        (
            {"common_crawl_warc_filename": "crawl-data/../escape.warc.gz"},
            "invalid_common_crawl_warc_filename",
        ),
        (
            {
                "common_crawl_warc_filename": (
                    f"crawl-data/{CC_COLLECTION}/%2E%2E/escape.warc.gz"
                ),
            },
            "invalid_common_crawl_warc_filename",
        ),
        ({"common_crawl_warc_offset": True}, "invalid_common_crawl_warc_offset"),
        ({"common_crawl_warc_length": 0}, "invalid_common_crawl_warc_length"),
        ({"common_crawl_collection": "CC-MAIN-other"}, "common_crawl_collection_mismatch"),
        (
            {"archive_url": CC_ARCHIVE_URL.replace("example.warc.gz", "other.warc.gz")},
            "common_crawl_warc_mismatch",
        ),
    ],
)
def test_common_crawl_pointer_object_range_and_target_fail_closed(
    changes: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(_common_crawl_receipt(**changes))
    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (
            {"common_crawl_warc_filename": _FilenameStringifier()},
            "invalid_common_crawl_warc_filename",
        ),
        (
            {"common_crawl_warc_offset": _IntegerSubclass(1234)},
            "invalid_common_crawl_warc_offset",
        ),
        (
            {"common_crawl_warc_length": _IntegerSubclass(567)},
            "invalid_common_crawl_warc_length",
        ),
    ],
)
def test_common_crawl_programmatic_mapping_values_are_not_coerced(
    changes: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(_common_crawl_receipt(**changes))
    assert exc_info.value.code == code


def test_common_crawl_retains_documented_http_https_original_equivalence_only() -> None:
    receipt = _common_crawl_receipt(
        common_crawl_indexed_url=OFFICIAL_URL.replace("https://", "http://", 1)
    )
    assert verify_state_law_transport_receipt(receipt).common_crawl_indexed_url.startswith("http://")


@pytest.mark.parametrize(
    ("receipt", "code"),
    [
        (
            {
                "content_sha256": BODY_SHA256,
                "official_url": OFFICIAL_URL,
                "source_transport": "direct",
                **_wayback_discovery_fields(),
            },
            "wayback_cdx_evidence_transport_mismatch",
        ),
        (
            _wayback_receipt(
                **{
                    key: value
                    for key, value in _common_crawl_receipt().items()
                    if key.startswith("common_crawl_")
                }
            ),
            "common_crawl_pointer_transport_mismatch",
        ),
        (
            _common_crawl_receipt(**_wayback_discovery_fields()),
            "wayback_cdx_evidence_transport_mismatch",
        ),
    ],
)
def test_optional_archive_evidence_cannot_move_to_another_transport(
    receipt: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(StateLawTransportReceiptError) as exc_info:
        verify_state_law_transport_receipt(receipt)
    assert exc_info.value.code == code
