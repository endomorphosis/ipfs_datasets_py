"""Bounds, SSRF, and raw-custody regressions for wallet processors (WALPROC-G630)."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.wallets.models import RawPayloadPolicy
from ipfs_datasets_py.processors.wallets.protocols import OperationContext, RequestLimits
from ipfs_datasets_py.processors.wallets.security import (
    EndpointPolicy,
    endpoint_fingerprint,
    safe_exception_text,
)
from ipfs_datasets_py.processors.wallets.storage import (
    DirectoryRawPayloadStore,
    InMemoryRawPayloadStore,
    RawPayloadCustodyLimits,
)
from ipfs_datasets_py.processors.wallets.worldcoin.config import (
    WORLD_ID_ENDPOINT_POLICY,
    WorldIdConfig,
    WorldIdConfigError,
    validate_verify_base_url,
    validate_world_id_resolved_addresses,
)


ENDPOINT = "https://rpc.wallet-provider.example/private/path"
CANARY_BODY = b"walproc-g630-bounds-body-fixture"


def _context() -> OperationContext:
    return OperationContext(
        request_id="walproc-g630-bounds",
        limits=RequestLimits(
            max_items=8,
            max_pages=2,
            max_requests=4,
            max_response_bytes=4_096,
        ),
    )


def _run(coro):
    return asyncio.run(coro)


def test_endpoint_policy_rejects_userinfo_secret_query_and_unsafe_hosts() -> None:
    policy = EndpointPolicy(
        allowed_hosts=frozenset({"rpc.wallet-provider.example"}),
        allowed_ports=frozenset({443}),
    )
    policy.validate_url("https://rpc.wallet-provider.example/v1")

    rejected = (
        "https://user:x@rpc.wallet-provider.example/v1",
        "https://rpc.wallet-provider.example/v1#frag",
        "http://rpc.wallet-provider.example/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://rpc.wallet-provider.example.internal/v1",
        "https://evil.example/v1",
        "https://rpc.wallet-provider.example:8443/v1",
    )
    for url in rejected:
        with pytest.raises(InvalidRequestError) as caught:
            policy.validate_url(url)
        message = str(caught.value)
        # Full endpoints stay out of operator-visible text.
        assert "rpc.wallet-provider.example" not in message
        assert "endpoint:" in message or "provider endpoint" in message

    # Secret-bearing query keys (token query without password/api_key assignment form).
    with pytest.raises(InvalidRequestError, match="credentials are forbidden"):
        policy.validate_url("https://rpc.wallet-provider.example/v1?token=fixture")


def test_endpoint_policy_rejects_non_global_dns_answers_without_echoing_url() -> None:
    policy = EndpointPolicy(allowed_hosts=frozenset({"rpc.wallet-provider.example"}))
    with pytest.raises(InvalidRequestError, match="DNS answer is unsafe") as caught:
        policy.validate_resolved_addresses(ENDPOINT, ["127.0.0.1"])
    assert ENDPOINT not in str(caught.value)
    assert endpoint_fingerprint(ENDPOINT) in str(caught.value)

    with pytest.raises(InvalidRequestError, match="DNS answer is unsafe"):
        policy.validate_resolved_addresses(ENDPOINT, ["169.254.169.254"])

    with pytest.raises(InvalidRequestError, match="DNS answer is unsafe"):
        policy.validate_resolved_addresses(ENDPOINT, ["10.0.0.8"])


def test_safe_exception_text_uses_fingerprint_only() -> None:
    text = safe_exception_text("bounded failure", endpoint=ENDPOINT)
    assert ENDPOINT not in text
    assert endpoint_fingerprint(ENDPOINT) in text
    assert text.startswith("bounded failure")


def test_request_limits_reject_non_positive_budgets() -> None:
    with pytest.raises((InvalidRequestError, TypeError, ValueError)):
        RequestLimits(
            max_items=0,
            max_pages=1,
            max_requests=1,
            max_response_bytes=1_024,
        )
    limits = RequestLimits(
        max_items=8,
        max_pages=2,
        max_requests=4,
        max_response_bytes=4_096,
    )
    assert limits.max_items == 8
    assert limits.max_response_bytes == 4_096


def test_inmemory_raw_store_enforces_object_total_and_count_before_mutation() -> None:
    store = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=16,
            max_total_bytes=40,
            max_objects=2,
        )
    )
    context = _context()

    with pytest.raises(ResourceLimitError, match="max_object_bytes"):
        _run(store.put(b"x" * 17, context=context))
    assert len(store) == 0
    assert store.total_bytes == 0

    _run(store.put(b"one", context=context))
    _run(store.put(b"two", context=context))
    assert len(store) == 2

    with pytest.raises(ResourceLimitError, match="max_objects"):
        _run(store.put(b"three", context=context))
    assert len(store) == 2

    small = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=16,
            max_total_bytes=20,
            max_objects=8,
        )
    )
    _run(small.put(b"abcdefghij", context=context))
    with pytest.raises(ResourceLimitError, match="max_total_bytes"):
        _run(small.put(b"abcdefghijk", context=context))
    assert len(small) == 1


def test_directory_raw_store_uses_restrictive_permissions_and_bounds(
    tmp_path: Path,
) -> None:
    store = DirectoryRawPayloadStore(
        tmp_path / "raw",
        limits=RawPayloadCustodyLimits(
            max_object_bytes=64,
            max_total_bytes=128,
            max_objects=4,
        ),
    )
    context = _context()
    ref = _run(store.put(CANARY_BODY, context=context))
    assert ref.digest.startswith("sha256:")
    mode = (tmp_path / "raw").stat().st_mode
    assert stat.S_IMODE(mode) & 0o077 == 0

    with pytest.raises(ResourceLimitError):
        _run(store.put(b"y" * 65, context=context))


def test_encrypted_raw_store_fails_closed_without_encryptor(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError, match="encryptor"):
        DirectoryRawPayloadStore(
            tmp_path / "enc",
            policy=RawPayloadPolicy.SEPARATELY_ENCRYPTED,
            encryptor=None,
            limits=RawPayloadCustodyLimits(
                max_object_bytes=64,
                max_total_bytes=128,
                max_objects=2,
            ),
        )


def test_world_id_verify_endpoint_policy_is_https_and_fingerprint_only() -> None:
    # Default World ID policy accepts the official developer host only.
    validate_verify_base_url("https://developer.world.org")
    with pytest.raises(WorldIdConfigError):
        validate_verify_base_url("http://developer.world.org")
    with pytest.raises(WorldIdConfigError):
        validate_verify_base_url("https://127.0.0.1/v1")

    config = WorldIdConfig(
        enabled=False,
        verify_base_url="https://developer.world.org",
    )
    public = config.public_dict()
    assert "developer.world.org" not in str(public.get("verify_base_url", ""))
    assert public["verify_endpoint_id"].startswith("endpoint:")
    assert config.http_timeout_seconds > 0
    assert config.max_request_bytes > 0
    assert config.max_response_bytes > 0
    assert config.max_decompressed_bytes > 0
    assert config.max_attempts >= 1

    with pytest.raises(WorldIdConfigError, match="DNS answer is unsafe"):
        validate_world_id_resolved_addresses(
            "https://developer.world.org",
            ["169.254.169.254"],
        )
    assert isinstance(WORLD_ID_ENDPOINT_POLICY, EndpointPolicy)
