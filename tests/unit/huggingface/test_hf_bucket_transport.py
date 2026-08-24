from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

from ipfs_datasets_py.huggingface.bucket import (
    HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION,
    HuggingFaceBucketListing,
    HuggingFaceBucketListingObject,
)
from ipfs_datasets_py.huggingface.hf_bucket_transport import (
    DEFAULT_OPEN_US_LAW_BUCKET_ID,
    DEFAULT_OPEN_US_LAW_BUDGETS,
    HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION,
    OPEN_US_LAW_ABSENT_JURISDICTIONS,
    OPEN_US_LAW_OBSERVED_OBJECT_COUNT,
    OPEN_US_LAW_OBSERVED_PARQUET_COUNT,
    OPEN_US_LAW_OBSERVED_TOTAL_BYTES,
    HuggingFaceBucketBudgetError,
    HuggingFaceBucketBudgets,
    HuggingFaceBucketContentRootReceipt,
    HuggingFaceBucketIntegrityError,
    HuggingFaceBucketListingDriftError,
    HuggingFaceBucketPathError,
    HuggingFaceBucketTransport,
    HuggingFaceBucketTransportError,
    listing_from_mapping,
    load_expected_listing,
    parse_hf_bucket_uri,
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_ir"
    / "open_us_law_bucket_listing.json"
)
_XET_README = "61" * 32
_XET_SHA256SUMS = "62" * 32
_XET_AL = "63" * 32
_XET_DC = "64" * 32
_XET_USCODE = "65" * 32
_README = b"# open-us-law seed snapshot\n" + b"." * 100
assert len(_README) == 128


def _tiny_budgets(**changes: int) -> HuggingFaceBucketBudgets:
    values = {
        "max_objects": 8,
        "max_bytes": 16_384,
        "max_object_bytes": 8_192,
        "max_range_bytes": 4_096,
    }
    values.update(changes)
    return HuggingFaceBucketBudgets(**values)


def _raw_objects() -> list[dict[str, object]]:
    return [
        {
            "type": "file",
            "path": "README.md",
            "size": 128,
            "xetHash": _XET_README,
            "contentType": "text/markdown",
            "mtime": "2026-07-21T00:00:00Z",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
        {
            "type": "file",
            "path": "SHA256SUMS.json",
            "size": 256,
            "xetHash": _XET_SHA256SUMS,
            "contentType": "application/json",
            "mtime": "2026-07-21T00:00:00Z",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
        {
            "type": "file",
            "path": "statutes/al.parquet",
            "size": 2048,
            "xetHash": _XET_AL,
            "contentType": "application/vnd.apache.parquet",
            "mtime": "2026-07-21T00:00:00Z",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
        {
            "type": "file",
            "path": "statutes/dc.parquet",
            "size": 1024,
            "xetHash": _XET_DC,
            "contentType": "application/vnd.apache.parquet",
            "mtime": "2026-07-21T00:00:00Z",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
        {
            "type": "file",
            "path": "federal/uscode.parquet",
            "size": 4096,
            "xetHash": _XET_USCODE,
            "contentType": "application/vnd.apache.parquet",
            "mtime": "2026-07-21T00:00:00Z",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
        {
            "type": "directory",
            "path": "statutes",
            "uploadedAt": "2026-07-21T00:00:00Z",
        },
    ]


class _ListClient:
    def __init__(self, objects: list[dict[str, object]] | None = None) -> None:
        self.objects = objects if objects is not None else _raw_objects()
        self.list_calls: list[dict[str, object]] = []

    def list_bucket_tree(
        self,
        *,
        bucket_id: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> list[dict[str, object]]:
        self.list_calls.append(
            {"bucket_id": bucket_id, "prefix": prefix, "recursive": recursive}
        )
        if not prefix:
            return list(self.objects)
        return [
            item
            for item in self.objects
            if str(item.get("path", "")) == prefix
            or str(item.get("path", "")).startswith(f"{prefix}/")
        ]


class _RangeClient(_ListClient):
    def __init__(
        self,
        objects: list[dict[str, object]] | None = None,
        payloads: dict[str, bytes] | None = None,
    ) -> None:
        super().__init__(objects)
        self.payloads = payloads or {"README.md": _README}
        self.range_calls: list[dict[str, object]] = []

    def range_read_bucket_file(
        self,
        *,
        bucket_id: str,
        path: str,
        start: int,
        end: int,
        expected_xet_hash: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> dict[str, object]:
        self.range_calls.append(
            {
                "bucket_id": bucket_id,
                "path": path,
                "start": start,
                "end": end,
                "expected_xet_hash": expected_xet_hash,
                "expected_size_bytes": expected_size_bytes,
            }
        )
        payload = self.payloads[path]
        if expected_size_bytes is not None and len(payload) != expected_size_bytes:
            raise HuggingFaceBucketTransportError("pinned size mismatch")
        if expected_xet_hash is not None:
            listed = next(item for item in self.objects if item.get("path") == path)
            if listed.get("xetHash") != expected_xet_hash:
                raise HuggingFaceBucketTransportError("pinned Xet mismatch")
        return {
            "bytes": payload[start:end],
            "xet_hash": expected_xet_hash or self.objects[0]["xetHash"],
            "size_bytes": len(payload),
        }


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        status: int = 206,
        url: str = "https://huggingface.co/response",
    ) -> None:
        self._payload = io.BytesIO(payload)
        self.headers = headers or {}
        self.status = status
        self.code = status
        self._url = url
        self.read_calls = 0

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        return self._payload.read(size)

    def geturl(self) -> str:
        return self._url


class _Opener:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[Request, float]] = []

    def open(self, request: Request, *, timeout: float) -> _Response:
        self.calls.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


class _HttpClient:
    def __init__(self, opener: _Opener, *, token: str | None = None) -> None:
        self.opener = opener
        self.endpoint = "https://huggingface.co"
        self.timeout_seconds = 15.0
        self.token = token
        self.user_agent = "ipfs-datasets-py/huggingface-bucket-transport-test"
        self.objects = _raw_objects()

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def list_bucket_tree(self, **_kwargs: object) -> list[dict[str, object]]:
        return list(self.objects)


def _fixture_payload() -> dict[str, object]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_listing() -> HuggingFaceBucketListing:
    return load_expected_listing(_FIXTURE_PATH)


def test_fixture_is_a_compact_unauthoritative_open_us_law_listing() -> None:
    payload = _fixture_payload()
    listing = listing_from_mapping(payload)
    observation = payload["observation"]

    assert listing.bucket_id == DEFAULT_OPEN_US_LAW_BUCKET_ID
    assert listing.schema_version == HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION
    assert listing.object_count == 5
    assert listing.total_size_bytes == 128 + 256 + 2048 + 1024 + 4096
    assert [item.path for item in listing.objects] == [
        "README.md",
        "SHA256SUMS.json",
        "federal/uscode.parquet",
        "statutes/al.parquet",
        "statutes/dc.parquet",
    ]
    assert "statutes/ga.parquet" not in {item.path for item in listing.objects}
    assert "statutes/nc.parquet" not in {item.path for item in listing.objects}
    assert observation["live_object_count"] == OPEN_US_LAW_OBSERVED_OBJECT_COUNT
    assert observation["live_parquet_count"] == OPEN_US_LAW_OBSERVED_PARQUET_COUNT
    assert observation["live_total_size_bytes"] == OPEN_US_LAW_OBSERVED_TOTAL_BYTES
    assert tuple(observation["absent_jurisdictions"]) == OPEN_US_LAW_ABSENT_JURISDICTIONS
    assert observation["grants_authority"] is False
    assert HuggingFaceBucketListing.from_json(listing.to_json()) == listing
    assert len(listing.listing_sha256) == 64


def test_parse_hf_bucket_uri_accepts_object_and_listing_forms() -> None:
    listing_ref = parse_hf_bucket_uri("hf://buckets/justicedao/open-us-law-bucket")
    object_ref = parse_hf_bucket_uri(
        "hf://buckets/justicedao/open-us-law-bucket/statutes/al.parquet"
        f"?listing_sha256={'ab' * 32}&xet_hash={_XET_AL}&size_bytes=2048"
    )

    assert listing_ref.bucket_id == DEFAULT_OPEN_US_LAW_BUCKET_ID
    assert listing_ref.path == ""
    assert object_ref.path == "statutes/al.parquet"
    assert object_ref.listing_sha256 == "ab" * 32
    assert object_ref.expected_xet_hash == _XET_AL
    assert object_ref.expected_size_bytes == 2048
    assert object_ref.uri.startswith("hf://buckets/justicedao/open-us-law-bucket/statutes/al.parquet")


@pytest.mark.parametrize(
    "uri",
    [
        "https://huggingface.co/buckets/justicedao/open-us-law-bucket/README.md",
        "hf://datasets/justicedao/open-us-law-bucket/README.md",
        "hf://buckets/justicedao/open-us-law-bucket/../secret",
        "hf://buckets/justicedao/open-us-law-bucket/%2e%2e/secret",
        "hf://buckets/justicedao/open-us-law-bucket/foo/../../etc/passwd",
        "hf://buckets/justicedao/open-us-law-bucket//foo",
        "hf://buckets/../evil/bucket/README.md",
        "hf://buckets/justicedao/open-us-law-bucket/foo\\bar",
        "hf://user@buckets/justicedao/open-us-law-bucket/README.md",
        "hf://buckets/justicedao/open-us-law-bucket/README.md#frag",
    ],
)
def test_parse_hf_bucket_uri_rejects_escapes_and_non_bucket_forms(uri: str) -> None:
    with pytest.raises(HuggingFaceBucketPathError):
        parse_hf_bucket_uri(uri)


def test_list_enforces_budgets_and_emits_content_root_receipt() -> None:
    expected = _fixture_listing()
    transport = HuggingFaceBucketTransport(
        client=_ListClient(),
        budgets=_tiny_budgets(),
        expected_listing=expected,
    )

    listing = transport.list("hf://buckets/justicedao/open-us-law-bucket")
    receipt = transport.snapshot("hf://buckets/justicedao/open-us-law-bucket")

    assert listing == expected
    assert receipt.listing_sha256 == expected.listing_sha256
    assert receipt.content_root == expected.listing_sha256
    assert receipt.grants_authority is False
    assert receipt.schema_version == HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION
    assert receipt.object_count == 5
    assert receipt.total_size_bytes == expected.total_size_bytes
    assert receipt.receipt_id.startswith("b")
    assert "token" not in receipt.to_json()
    assert "Authorization" not in receipt.to_json()
    assert HuggingFaceBucketContentRootReceipt.from_json(receipt.to_json()) == receipt
    assert receipt.identity.cid == receipt.receipt_id


def test_list_rejects_object_and_byte_budget_overrun() -> None:
    objects = _raw_objects()
    too_many = HuggingFaceBucketTransport(
        client=_ListClient(objects),
        budgets=_tiny_budgets(max_objects=2),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )
    too_large = HuggingFaceBucketTransport(
        client=_ListClient(objects),
        budgets=_tiny_budgets(max_bytes=512, max_object_bytes=256, max_range_bytes=256),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )
    oversized_object = HuggingFaceBucketTransport(
        client=_ListClient(objects),
        budgets=_tiny_budgets(max_object_bytes=512, max_range_bytes=512),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )

    with pytest.raises(HuggingFaceBucketBudgetError, match="max_objects"):
        too_many.list()
    with pytest.raises(HuggingFaceBucketBudgetError, match="max_bytes"):
        too_large.list()
    with pytest.raises(HuggingFaceBucketBudgetError, match="max_object_bytes"):
        oversized_object.list()


def test_list_rejects_path_size_and_xet_listing_drift() -> None:
    expected = _fixture_listing()
    added = _raw_objects() + [
        {
            "type": "file",
            "path": "statutes/ga.parquet",
            "size": 8,
            "xetHash": "67" * 32,
            "contentType": "application/vnd.apache.parquet",
        }
    ]
    removed = [item for item in _raw_objects() if item.get("path") != "statutes/dc.parquet"]
    resized = []
    for item in _raw_objects():
        row = dict(item)
        if row.get("path") == "README.md":
            row["size"] = 64
        resized.append(row)
    retargeted = []
    for item in _raw_objects():
        row = dict(item)
        if row.get("path") == "README.md":
            row["xetHash"] = "ff" * 32
        retargeted.append(row)

    for objects, _reason in (
        (added, "added"),
        (removed, "removed"),
        (resized, "changed"),
        (retargeted, "changed"),
    ):
        transport = HuggingFaceBucketTransport(
            client=_ListClient(objects),
            budgets=_tiny_budgets(),
            expected_listing=expected,
        )
        with pytest.raises(HuggingFaceBucketListingDriftError, match="listing drift"):
            transport.list()


def test_list_rejects_uri_listing_digest_pin_drift() -> None:
    transport = HuggingFaceBucketTransport(
        client=_ListClient(),
        budgets=_tiny_budgets(),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )
    with pytest.raises(HuggingFaceBucketListingDriftError, match="listing_sha256"):
        transport.list(
            f"hf://buckets/justicedao/open-us-law-bucket?listing_sha256={'00' * 32}"
        )


def test_range_read_verifies_xet_identity_and_size() -> None:
    expected = _fixture_listing()
    client = _RangeClient()
    transport = HuggingFaceBucketTransport(
        client=client,
        budgets=_tiny_budgets(),
        expected_listing=expected,
    )

    result = transport.range_read(
        "hf://buckets/justicedao/open-us-law-bucket/README.md",
        start=0,
        end=16,
    )

    assert result.payload == _README[:16]
    assert result.sha256 == hashlib.sha256(_README[:16]).hexdigest()
    assert result.xet_hash == _XET_README
    assert result.identity_kind == "xet"
    assert result.object_size_bytes == 128
    assert result.size_bytes == 16
    assert client.range_calls[0]["expected_xet_hash"] == _XET_README
    assert client.range_calls[0]["expected_size_bytes"] == 128
    assert transport.bytes_consumed == 16
    assert transport.objects_read == 1


def test_range_read_verifies_sha256_of_returned_bytes(tmp_path: Path) -> None:
    payload = _README
    digest = hashlib.sha256(payload).hexdigest()
    client = _RangeClient()
    transport = HuggingFaceBucketTransport(
        client=client,
        budgets=_tiny_budgets(),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )
    destination = tmp_path / "README.md"

    result = transport.range_read(
        (
            "hf://buckets/justicedao/open-us-law-bucket/README.md"
            f"?sha256={digest}&size_bytes=128"
        ),
        start=0,
        end=128,
        destination=destination,
    )

    assert result.identity_kind == "sha256"
    assert result.payload == payload
    assert destination.read_bytes() == payload
    with pytest.raises(HuggingFaceBucketTransportError, match="must not already exist"):
        transport.range_read(
            f"hf://buckets/justicedao/open-us-law-bucket/README.md?sha256={digest}",
            start=0,
            end=128,
            destination=destination,
        )


def test_range_read_rejects_missing_identity_and_mismatches() -> None:
    transport = HuggingFaceBucketTransport(
        client=_RangeClient(),
        budgets=_tiny_budgets(),
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
    )

    with pytest.raises(HuggingFaceBucketIntegrityError, match="SHA256 or Xet"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/README.md",
            start=0,
            end=8,
        )
    with pytest.raises(HuggingFaceBucketIntegrityError, match="sha256 mismatch"):
        transport.range_read(
            f"hf://buckets/justicedao/open-us-law-bucket/README.md?sha256={'00' * 32}",
            start=0,
            end=8,
        )
    with pytest.raises(HuggingFaceBucketIntegrityError, match="extends past"):
        transport.range_read(
            (
                "hf://buckets/justicedao/open-us-law-bucket/README.md"
                f"?xet_hash={_XET_README}&size_bytes=128"
            ),
            start=0,
            end=256,
        )


def test_range_read_rejects_budget_overrun_and_path_escape() -> None:
    transport = HuggingFaceBucketTransport(
        client=_RangeClient(),
        budgets=_tiny_budgets(max_range_bytes=8, max_objects=1),
        expected_listing=_fixture_listing(),
    )

    with pytest.raises(HuggingFaceBucketBudgetError, match="max_range_bytes"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/README.md",
            start=0,
            end=16,
        )
    with pytest.raises(HuggingFaceBucketPathError):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/../README.md",
            start=0,
            end=4,
        )
    first = transport.range_read(
        "hf://buckets/justicedao/open-us-law-bucket/README.md",
        start=0,
        end=4,
    )
    assert first.size_bytes == 4
    with pytest.raises(HuggingFaceBucketBudgetError, match="max_objects"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/statutes/al.parquet",
            start=0,
            end=4,
        )


def test_range_read_rejects_object_absent_from_pinned_listing() -> None:
    transport = HuggingFaceBucketTransport(
        client=_RangeClient(
            payloads={"statutes/ga.parquet": b"missing"},
            objects=_raw_objects()
            + [
                {
                    "type": "file",
                    "path": "statutes/ga.parquet",
                    "size": 7,
                    "xetHash": "67" * 32,
                    "contentType": "application/vnd.apache.parquet",
                }
            ],
        ),
        budgets=_tiny_budgets(),
        expected_listing=_fixture_listing(),
    )
    with pytest.raises(HuggingFaceBucketListingDriftError, match="not present"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/statutes/ga.parquet",
            start=0,
            end=4,
        )


def test_http_range_read_sends_range_header_and_checks_content_range() -> None:
    payload = _README[:16]
    response = _Response(
        payload,
        headers={
            "Content-Range": "bytes 0-15/128",
            "X-Xet-Hash": _XET_README,
        },
        status=206,
    )
    opener = _Opener([response])
    transport = HuggingFaceBucketTransport(
        client=_HttpClient(opener, token="secret"),
        budgets=_tiny_budgets(),
        expected_listing=_fixture_listing(),
    )

    result = transport.range_read(
        "hf://buckets/justicedao/open-us-law-bucket/README.md",
        start=0,
        end=16,
    )

    assert result.payload == payload
    request, timeout = opener.calls[0]
    assert timeout == 15.0
    assert request.get_header("Range") == "bytes=0-15"
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.full_url.endswith(
        "/buckets/justicedao/open-us-law-bucket/resolve/README.md"
    )


def test_http_range_read_rejects_content_range_and_xet_drift() -> None:
    opener = _Opener(
        [
            _Response(
                _README[:16],
                headers={
                    "Content-Range": "bytes 0-31/128",
                    "X-Xet-Hash": _XET_README,
                },
            )
        ]
    )
    transport = HuggingFaceBucketTransport(
        client=_HttpClient(opener),
        budgets=_tiny_budgets(),
        expected_listing=_fixture_listing(),
    )
    with pytest.raises(HuggingFaceBucketIntegrityError, match="Content-Range"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/README.md",
            start=0,
            end=16,
        )

    opener = _Opener(
        [
            _Response(
                _README[:16],
                headers={
                    "Content-Range": "bytes 0-15/128",
                    "X-Xet-Hash": _XET_AL,
                },
            )
        ]
    )
    transport = HuggingFaceBucketTransport(
        client=_HttpClient(opener),
        budgets=_tiny_budgets(),
        expected_listing=_fixture_listing(),
    )
    with pytest.raises(HuggingFaceBucketIntegrityError, match="Xet"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/README.md",
            start=0,
            end=16,
        )


def test_http_range_read_rejects_full_body_when_partial_range_requested() -> None:
    opener = _Opener(
        [
            _Response(
                _README,
                headers={"X-Xet-Hash": _XET_README, "Content-Length": "128"},
                status=200,
            )
        ]
    )
    transport = HuggingFaceBucketTransport(
        client=_HttpClient(opener),
        budgets=_tiny_budgets(),
        expected_listing=_fixture_listing(),
    )
    with pytest.raises(HuggingFaceBucketIntegrityError, match="ignored Range"):
        transport.range_read(
            "hf://buckets/justicedao/open-us-law-bucket/README.md",
            start=4,
            end=12,
        )


def test_default_open_us_law_budgets_cover_observed_live_bucket() -> None:
    assert DEFAULT_OPEN_US_LAW_BUDGETS.max_objects >= OPEN_US_LAW_OBSERVED_OBJECT_COUNT
    assert DEFAULT_OPEN_US_LAW_BUDGETS.max_bytes >= OPEN_US_LAW_OBSERVED_TOTAL_BYTES
    assert DEFAULT_OPEN_US_LAW_BUDGETS.max_object_bytes <= DEFAULT_OPEN_US_LAW_BUDGETS.max_bytes
    assert DEFAULT_OPEN_US_LAW_BUDGETS.max_range_bytes <= DEFAULT_OPEN_US_LAW_BUDGETS.max_bytes


def test_receipt_rejects_authority_and_unknown_fields() -> None:
    listing = _fixture_listing()
    transport = HuggingFaceBucketTransport(
        client=_ListClient(),
        budgets=_tiny_budgets(),
        expected_listing=listing,
    )
    receipt = transport.snapshot()
    payload = receipt.to_dict()
    payload["grants_authority"] = True
    with pytest.raises(HuggingFaceBucketTransportError, match="must not grant authority"):
        HuggingFaceBucketContentRootReceipt.from_dict(payload)
    payload = receipt.to_dict()
    payload["token"] = "secret"
    with pytest.raises(HuggingFaceBucketTransportError, match="unknown or missing"):
        HuggingFaceBucketContentRootReceipt.from_dict(payload)


def test_list_prefix_is_confined_and_drift_checked() -> None:
    prefix_objects = [
        item
        for item in _raw_objects()
        if str(item.get("path", "")).startswith("statutes/")
        or item.get("path") == "statutes"
    ]
    expected = HuggingFaceBucketListing(
        bucket_id=DEFAULT_OPEN_US_LAW_BUCKET_ID,
        prefix="statutes",
        objects=tuple(
            HuggingFaceBucketListingObject.from_source(item)
            for item in prefix_objects
            if item.get("type") != "directory"
        ),
    )
    transport = HuggingFaceBucketTransport(
        client=_ListClient(_raw_objects()),
        budgets=_tiny_budgets(),
        expected_listing=expected,
    )
    listing = transport.list("hf://buckets/justicedao/open-us-law-bucket/statutes")
    assert [item.path for item in listing.objects] == [
        "statutes/al.parquet",
        "statutes/dc.parquet",
    ]
    with pytest.raises(HuggingFaceBucketListingDriftError, match="prefix"):
        transport.list("hf://buckets/justicedao/open-us-law-bucket")
