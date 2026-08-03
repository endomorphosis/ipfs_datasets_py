"""Security: private embedding runtime makes zero external calls and discloses nothing.

PATLAW-145 acceptance:
* confidential / private routes make zero external calls
* receipts, logs, and diagnostics disclose no text, vectors, or CIDs
"""

from __future__ import annotations

import io
import json
import logging
import socket
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.embedding_runtime import (
    CODE_DIGEST,
    PINNED_MODEL_ID,
    CancellationToken,
    DeviceFallbackPolicy,
    EmbeddingRuntimeConfig,
    LocalEmbeddingRuntime,
    PolicyDecisionCode,
    evaluate_embedding_policy,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    DisclosureClass,
)

# Synthetic canaries — not live matter content.
PRIVATE_TEXT_CANARY = (
    "CONFIDENTIAL unpublished claim language embedding-canary-9f3a-PRIVATE-BODY"
)
PRIVATE_CID_CANARY = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
PRIVATE_VECTOR_MARKER = 0.424242424242


class _RemoteCallTrap:
    """Record and block any attempt to open a network connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        raise OSError("remote network blocked by private embedding non-disclosure trap")


@pytest.fixture
def remote_trap(monkeypatch: pytest.MonkeyPatch) -> _RemoteCallTrap:
    trap = _RemoteCallTrap()
    monkeypatch.setattr(socket.socket, "connect", trap)
    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        lambda self, *a, **k: trap(*a, **k) or 1,
    )
    try:
        import urllib.request as urllib_request

        monkeypatch.setattr(urllib_request, "urlopen", trap)
    except Exception:  # noqa: BLE001
        pass
    try:
        import http.client as http_client

        monkeypatch.setattr(http_client.HTTPConnection, "request", trap)
        monkeypatch.setattr(http_client.HTTPSConnection, "request", trap)
    except Exception:  # noqa: BLE001
        pass
    return trap


def _capture_logging() -> tuple[io.StringIO, logging.Handler, int]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return stream, handler, previous_level


def _release_logging(
    stream: io.StringIO, handler: logging.Handler, previous_level: int
) -> str:
    root = logging.getLogger()
    root.removeHandler(handler)
    root.setLevel(previous_level)
    return stream.getvalue()


def _serialize_surfaces(result: Any) -> str:
    """Flatten receipt / result surfaces into a searchable string."""
    chunks: list[str] = []
    if hasattr(result, "to_dict"):
        chunks.append(json.dumps(result.to_dict(), sort_keys=True, default=str))
    if hasattr(result, "receipt"):
        chunks.append(
            json.dumps(result.receipt.to_dict(), sort_keys=True, default=str)
        )
        chunks.append(
            json.dumps(result.receipt.policy.to_dict(), sort_keys=True, default=str)
        )
        chunks.append(
            json.dumps(result.receipt.identity.to_dict(), sort_keys=True, default=str)
        )
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Zero external calls
# ---------------------------------------------------------------------------


def test_confidential_embed_makes_zero_external_calls(
    remote_trap: _RemoteCallTrap,
) -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(allow_remote=False, redact_private_receipts=True)
    )
    result = runtime.embed(
        [PRIVATE_TEXT_CANARY],
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        remote_requested=True,
    )
    assert remote_trap.calls == []
    assert runtime.external_call_count == 0
    assert result.receipt.policy.private_route is True
    assert result.receipt.policy.code in {
        PolicyDecisionCode.DENY_REMOTE_PRIVATE,
        PolicyDecisionCode.DENY_REMOTE_DEFAULT,
    }
    # Still produces local vectors for index materialization.
    assert len(result.vectors) == 1
    assert len(result.vectors[0]) > 0


def test_privileged_and_export_review_zero_external_calls(
    remote_trap: _RemoteCallTrap,
) -> None:
    runtime = LocalEmbeddingRuntime()
    for disc in (
        DisclosureClass.PRIVILEGED_WORK_PRODUCT,
        DisclosureClass.RESTRICTED_EXPORT_REVIEW,
        DisclosureClass.CREDENTIAL_OR_PAYMENT,
    ):
        result = runtime.embed(
            [PRIVATE_TEXT_CANARY],
            disclosure=disc,
            remote_requested=True,
        )
        assert remote_trap.calls == []
        assert runtime.external_call_count == 0
        assert result.receipt.policy.private_route is True


def test_private_route_flag_forces_isolation_even_if_disclosure_public(
    remote_trap: _RemoteCallTrap,
) -> None:
    runtime = LocalEmbeddingRuntime()
    result = runtime.embed(
        [PRIVATE_TEXT_CANARY],
        disclosure=DisclosureClass.PUBLIC_USER,
        private_route=True,
        remote_requested=True,
    )
    assert remote_trap.calls == []
    assert runtime.external_call_count == 0
    assert result.receipt.policy.code == PolicyDecisionCode.DENY_REMOTE_PRIVATE


def test_allow_remote_true_still_never_calls_network(
    remote_trap: _RemoteCallTrap,
) -> None:
    """Pinned local runtime never executes nonlocal routes even if allowed."""
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(allow_remote=True)
    )
    result = runtime.embed(
        ["public text only"],
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        remote_requested=True,
    )
    assert remote_trap.calls == []
    assert runtime.external_call_count == 0
    assert len(result.vectors[0]) > 0


# ---------------------------------------------------------------------------
# Non-disclosure of text, vectors, CIDs
# ---------------------------------------------------------------------------


def test_private_receipt_redacts_text_vectors_and_cids(
    remote_trap: _RemoteCallTrap,
) -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(redact_private_receipts=True)
    )
    result = runtime.embed(
        [PRIVATE_TEXT_CANARY],
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
    )
    surface = _serialize_surfaces(result)
    assert PRIVATE_TEXT_CANARY not in surface
    assert PRIVATE_CID_CANARY not in surface
    # Vector values must not appear in receipt dicts.
    receipt = result.receipt.to_dict()
    assert receipt["redacted"] is True
    assert receipt["input_digests"] == []
    assert receipt["vector_digest"] == ""
    assert "vectors" not in receipt
    blob = json.dumps(receipt)
    assert PRIVATE_TEXT_CANARY not in blob
    assert PRIVATE_CID_CANARY not in blob
    # Receipt must not embed a vector array payload.
    assert "\"vectors\"" not in blob


def test_private_result_to_dict_never_includes_vectors_when_redacted() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(redact_private_receipts=True)
    )
    result = runtime.embed(
        [PRIVATE_TEXT_CANARY],
        disclosure=DisclosureClass.PRIVILEGED_WORK_PRODUCT,
    )
    # Even if a caller asks for vectors on a redacted private result, withhold.
    payload = result.to_dict(include_vectors=True)
    assert "vectors" not in payload
    assert PRIVATE_TEXT_CANARY not in json.dumps(payload)


def test_logs_do_not_disclose_private_text_vectors_or_cids(
    remote_trap: _RemoteCallTrap,
) -> None:
    stream, handler, previous = _capture_logging()
    try:
        runtime = LocalEmbeddingRuntime()
        runtime.embed(
            [PRIVATE_TEXT_CANARY],
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
            remote_requested=True,
        )
    finally:
        logs = _release_logging(stream, handler, previous)

    assert PRIVATE_TEXT_CANARY not in logs
    assert PRIVATE_CID_CANARY not in logs
    # Policy may log decision codes only.
    if "embedding_policy" in logs:
        assert "deny_remote" in logs or "decision=" in logs
    assert remote_trap.calls == []


def test_public_receipt_may_bind_digests_but_not_raw_text() -> None:
    runtime = LocalEmbeddingRuntime()
    public_text = "Public official abstract about CPC G06F16/00"
    result = runtime.embed(
        [public_text],
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
    )
    receipt = result.receipt.to_dict()
    assert receipt["redacted"] is False
    assert len(receipt["input_digests"]) == 1
    assert len(receipt["input_digests"][0]) == 64
    assert len(receipt["vector_digest"]) == 64
    blob = json.dumps(receipt)
    assert public_text not in blob
    assert PRIVATE_TEXT_CANARY not in blob


def test_error_messages_do_not_echo_private_text() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(max_text_chars=8)
    )
    with pytest.raises(Exception) as exc_info:
        runtime.embed(
            [PRIVATE_TEXT_CANARY],
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        )
    message = str(exc_info.value)
    assert PRIVATE_TEXT_CANARY not in message
    assert PRIVATE_CID_CANARY not in message


def test_cancellation_reason_safe_with_private_content() -> None:
    token = CancellationToken()
    token.cancel("operator-abort")
    runtime = LocalEmbeddingRuntime()
    with pytest.raises(Exception) as exc_info:
        runtime.embed(
            [PRIVATE_TEXT_CANARY],
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
            cancellation=token,
        )
    assert PRIVATE_TEXT_CANARY not in str(exc_info.value)


def test_policy_decision_surface_has_no_content_fields() -> None:
    decision = evaluate_embedding_policy(
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        remote_requested=True,
        allow_remote=True,
    )
    payload = decision.to_dict()
    allowed_keys = {
        "allow_execute",
        "code",
        "disclosure",
        "private_route",
        "reason",
        "route",
    }
    assert set(payload) == allowed_keys
    assert PRIVATE_TEXT_CANARY not in json.dumps(payload)
    assert "vector" not in json.dumps(payload).lower() or "vector" not in payload


def test_hardware_fallback_receipt_safe_for_private(
    remote_trap: _RemoteCallTrap,
) -> None:
    def probe(device: str) -> bool:
        return device == "cpu"

    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(
            device="cuda",
            device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
            redact_private_receipts=True,
        ),
        device_probe=probe,
    )
    result = runtime.embed(
        [PRIVATE_TEXT_CANARY],
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        remote_requested=True,
    )
    assert remote_trap.calls == []
    receipt = result.receipt.to_dict()
    assert receipt["device_fallback_applied"] is True
    assert receipt["device_selected"] == "cpu"
    assert receipt["redacted"] is True
    assert PRIVATE_TEXT_CANARY not in json.dumps(receipt)
    assert receipt["identity"]["model_id"] == PINNED_MODEL_ID
    assert receipt["identity"]["code_digest"] == CODE_DIGEST
