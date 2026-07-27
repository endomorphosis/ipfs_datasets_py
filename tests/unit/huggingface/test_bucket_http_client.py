from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

import ipfs_datasets_py.huggingface.bucket as bucket_module
from ipfs_datasets_py.huggingface.bucket import (
    HuggingFaceBucketError,
    HuggingFaceBucketHttpClient,
    HuggingFaceBucketListing,
    HuggingFaceBucketListingObject,
    HuggingFaceBucketStore,
    _SafeRedirectHandler,
)

_XET_A = "a" * 64
_XET_B = "b" * 64


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        url: str = "https://huggingface.co/response",
    ) -> None:
        self._payload = io.BytesIO(payload)
        self.headers = headers or {}
        self._url = url
        self.read_calls = 0
        self.read_sizes: list[int] = []

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        self.read_sizes.append(size)
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


class _ChunkedResponse(_Response):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        headers: dict[str, str] | None = None,
        url: str = "https://huggingface.co/response",
    ) -> None:
        super().__init__(b"", headers=headers, url=url)
        self._chunks = iter(chunks)

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        self.read_sizes.append(size)
        return next(self._chunks, b"")


def _listing_object(payload: bytes = b"raw audio") -> HuggingFaceBucketListingObject:
    return HuggingFaceBucketListingObject(
        path="runs/audio/abby.mp3",
        size_bytes=len(payload),
        xet_hash=_XET_A,
        media_type="audio/mpeg",
        mtime="2026-07-25T20:10:30.123+00:00",
        uploaded_at="2026-07-25T20:11:00Z",
    )


def test_http_listing_is_paginated_stable_and_explicitly_unverified() -> None:
    next_url = "/api/buckets/Publicus/abby-voice/tree/runs%2Faudio?recursive=true&cursor=next"
    first = [
        {
            "type": "directory",
            "path": "runs/audio/folder",
            "uploadedAt": "2026-07-25T20:00:00Z",
        },
        {
            "type": "file",
            "path": "runs/audio/b.mp3",
            "size": 2,
            "xetHash": _XET_B,
            "mtime": "2026-07-25T20:10:30.123Z",
            "uploadedAt": "2026-07-25T20:11:00Z",
            "contentType": "audio/mpeg",
        },
    ]
    second = [
        {
            "type": "file",
            "path": "runs/audio/a.wav",
            "size": 1,
            "xetHash": _XET_A,
            "mtime": None,
            "uploadedAt": None,
        }
    ]
    opener = _Opener(
        [
            _Response(
                json.dumps(first).encode(),
                headers={
                    "Link": (
                        '</ignored>; title="a comma, inside quotes"; rel=prev, '
                        f'<{next_url}>; type="application/json"; rel="NEXT alternate"'
                    )
                },
            ),
            _Response(json.dumps(second).encode()),
        ]
    )
    client = HuggingFaceBucketHttpClient(token="secret", opener=opener)

    listing = HuggingFaceBucketStore(
        "Publicus/abby-voice",
        client=client,
    ).discover(prefix="runs/audio")

    assert [item.path for item in listing.objects] == [
        "runs/audio/a.wav",
        "runs/audio/b.mp3",
    ]
    assert listing.objects[0].media_type == "audio/x-wav"
    assert listing.objects[1].xet_hash == _XET_B
    assert "sha256" not in listing.objects[1].to_dict()
    assert HuggingFaceBucketListing.from_json(listing.to_json()) == listing
    assert len(listing.listing_sha256) == 64
    assert len(opener.calls) == 2
    assert opener.calls[0][0].full_url.endswith("/api/buckets/Publicus/abby-voice/tree/runs%2Faudio?recursive=true")
    assert opener.calls[1][0].full_url == f"https://huggingface.co{next_url}"
    assert opener.calls[0][0].get_header("Authorization") == "Bearer secret"


def test_http_listing_rejects_pagination_loop_before_repeating_request() -> None:
    opener = _Opener(
        [
            _Response(
                b"[]",
                headers={"Link": '<?recursive=true>; rel="next"'},
            )
        ]
    )
    client = HuggingFaceBucketHttpClient(opener=opener)

    with pytest.raises(HuggingFaceBucketError, match="forms a loop"):
        client.list_bucket_tree(bucket_id="Publicus/abby-voice")

    assert len(opener.calls) == 1


def test_http_listing_enforces_page_cap_before_an_extra_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bucket_module, "_MAX_BUCKET_TREE_PAGES", 2)
    opener = _Opener(
        [
            _Response(
                b"[]",
                headers={
                    "Link": '<?recursive=true&cursor=one>; rel="next"'
                },
            ),
            _Response(
                b"[]",
                headers={
                    "Link": '<?recursive=true&cursor=two>; rel="next"'
                },
            ),
        ]
    )
    client = HuggingFaceBucketHttpClient(opener=opener)

    with pytest.raises(HuggingFaceBucketError, match="exceeded the page limit"):
        client.list_bucket_tree(bucket_id="Publicus/abby-voice")

    assert len(opener.calls) == 2


@pytest.mark.parametrize(
    ("link_header", "error"),
    [
        ("<https://evil.example/next>; rel=next", "changed origin"),
        ("</next>; rel", "parameter is malformed"),
        ("</one>; rel=next, </two>; rel=next", "multiple next links"),
    ],
)
def test_http_listing_rejects_unsafe_or_malformed_next_links(
    link_header: str,
    error: str,
) -> None:
    opener = _Opener([_Response(b"[]", headers={"Link": link_header})])
    client = HuggingFaceBucketHttpClient(opener=opener)

    with pytest.raises(HuggingFaceBucketError, match=error):
        client.list_bucket_tree(bucket_id="Publicus/abby-voice")

    assert len(opener.calls) == 1


def test_fetch_discovered_hashes_raw_bytes_and_requires_pinned_cache_evidence(
    tmp_path: Path,
) -> None:
    payload = b"raw audio"
    discovered = _listing_object(payload)
    opener = _Opener(
        [
            _Response(
                payload,
                headers={"X-Xet-Hash": discovered.xet_hash},
                url=f"https://cdn.example/xet/{discovered.xet_hash}",
            )
        ]
    )
    store = HuggingFaceBucketStore(
        "Publicus/abby-voice",
        client=HuggingFaceBucketHttpClient(opener=opener),
    )
    destination = tmp_path / "cache" / "abby.mp3"

    verified = store.fetch_discovered(discovered, destination)

    assert destination.read_bytes() == payload
    assert verified.sha256 == hashlib.sha256(payload).hexdigest()
    assert verified.sha256 != discovered.xet_hash
    assert verified.etag == f"hf-xet:{discovered.xet_hash}"
    assert len(opener.calls) == 1

    offline = HuggingFaceBucketStore("Publicus/abby-voice", client=object())
    with pytest.raises(HuggingFaceBucketError, match="must not already exist"):
        offline.fetch_discovered(discovered, destination)
    cache_hit = offline.verify_discovered_file(
        discovered,
        destination,
        expected_sha256=verified.sha256,
    )
    assert cache_hit == verified
    destination.write_bytes(b"x" * len(payload))
    with pytest.raises(HuggingFaceBucketError, match="sha256 mismatch"):
        offline.verify_discovered_file(
            discovered,
            destination,
            expected_sha256=verified.sha256,
        )
    assert len(opener.calls) == 1


def test_fetch_discovered_rejects_oversized_content_length_before_reading(
    tmp_path: Path,
) -> None:
    discovered = _listing_object(b"abc")
    response = _Response(
        b"abcd",
        headers={
            "Content-Length": "4",
            "X-Xet-Hash": discovered.xet_hash,
        },
        url=f"https://cdn.example/xet/{discovered.xet_hash}",
    )
    store = HuggingFaceBucketStore(
        "Publicus/abby-voice",
        client=HuggingFaceBucketHttpClient(opener=_Opener([response])),
    )

    with pytest.raises(HuggingFaceBucketError, match="Content-Length exceeds"):
        store.fetch_discovered(discovered, tmp_path / "abby.mp3")

    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_fetch_discovered_aborts_stream_immediately_after_size_limit(
    tmp_path: Path,
) -> None:
    discovered = _listing_object(b"abc")
    response = _ChunkedResponse(
        [b"abc", b"d", b"unread"],
        headers={
            "Content-Length": "3",
            "X-Xet-Hash": discovered.xet_hash,
        },
        url=f"https://cdn.example/xet/{discovered.xet_hash}",
    )
    store = HuggingFaceBucketStore(
        "Publicus/abby-voice",
        client=HuggingFaceBucketHttpClient(opener=_Opener([response])),
    )

    with pytest.raises(HuggingFaceBucketError, match="exceeded expected size"):
        store.fetch_discovered(discovered, tmp_path / "abby.mp3")

    assert response.read_calls == 2
    assert response.read_sizes == [4, 1]
    assert list(tmp_path.iterdir()) == []


def test_fetch_discovered_rejects_xet_mismatch_and_cleans_partial(
    tmp_path: Path,
) -> None:
    discovered = _listing_object()
    opener = _Opener(
        [
            _Response(
                b"raw audio",
                headers={"X-Xet-Hash": _XET_B},
                url=f"https://cdn.example/xet/{_XET_B}",
            )
        ]
    )
    store = HuggingFaceBucketStore(
        "Publicus/abby-voice",
        client=HuggingFaceBucketHttpClient(opener=opener),
    )

    with pytest.raises(HuggingFaceBucketError, match="Xet hash"):
        store.fetch_discovered(discovered, tmp_path / "abby.mp3")

    assert list(tmp_path.iterdir()) == []


def test_download_xet_binding_requires_exact_header_or_decoded_path_segment(
    tmp_path: Path,
) -> None:
    payload = b"raw audio"
    client = HuggingFaceBucketHttpClient(
        opener=_Opener(
            [
                _Response(
                    payload,
                    headers={"X-Xet-Hash": _XET_B},
                    url=f"https://cdn.example/xet/{_XET_A}suffix",
                ),
                _Response(
                    payload,
                    headers={"X-Xet-Hash": _XET_B},
                    url=f"https://cdn.example/xet/%61{_XET_A[1:]}",
                ),
                _Response(
                    payload,
                    headers={"X-Xet-Hash": _XET_A},
                    url="https://cdn.example/%ff",
                ),
            ]
        )
    )

    with pytest.raises(HuggingFaceBucketError, match="Xet hash"):
        client.download_bucket_file(
            bucket_id="Publicus/abby-voice",
            path="runs/audio/abby.mp3",
            destination=tmp_path / "suffix.mp3",
            expected_xet_hash=_XET_A,
            expected_size_bytes=len(payload),
        )

    assert not (tmp_path / "suffix.mp3").exists()
    assert (
        client.download_bucket_file(
            bucket_id="Publicus/abby-voice",
            path="runs/audio/abby.mp3",
            destination=tmp_path / "decoded-segment.mp3",
            expected_xet_hash=_XET_A,
            expected_size_bytes=len(payload),
        )
        == len(payload)
    )
    assert (
        client.download_bucket_file(
            bucket_id="Publicus/abby-voice",
            path="runs/audio/abby.mp3",
            destination=tmp_path / "header.mp3",
            expected_xet_hash=_XET_A,
            expected_size_bytes=len(payload),
        )
        == len(payload)
    )


def test_safe_redirect_drops_authorization_only_across_origins() -> None:
    handler = _SafeRedirectHandler()
    request = Request(
        "https://huggingface.co/buckets/Publicus/abby-voice/resolve/a.mp3",
        headers={"Authorization": "Bearer secret"},
    )

    cross_origin = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://cdn.example/xet/hash",
    )
    same_origin = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://huggingface.co/other",
    )

    assert cross_origin is not None
    assert cross_origin.get_header("Authorization") is None
    assert same_origin is not None
    assert same_origin.get_header("Authorization") == "Bearer secret"


def test_listing_rejects_xet_hash_as_a_short_or_ambiguous_digest() -> None:
    with pytest.raises(HuggingFaceBucketError, match="xet_hash"):
        HuggingFaceBucketListingObject(
            path="raw/a.wav",
            size_bytes=1,
            xet_hash="abc",
            media_type="audio/wav",
        )
