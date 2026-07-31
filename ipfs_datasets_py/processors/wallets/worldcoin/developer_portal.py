"""World Developer Portal verification client and response normalization.

Transport is injected via ``request_json`` so unit tests never open sockets.
The default transport reuses the shared :class:`EndpointPolicy`, enforces
finite request/response/decompression/retry/deadline budgets, rejects unsafe
DNS answers and redirects, and never chains untrusted upstream exceptions.

Verification results wrap identity material so raw nullifiers cannot cross
``repr`` or public serialization boundaries.
"""

from __future__ import annotations

import gzip
import io
import json
import socket
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.parse import urlsplit

from ipfs_datasets_py.processors.wallets.errors import InvalidRequestError
from ipfs_datasets_py.processors.wallets.security import (
    EndpointPolicy,
    safe_exception_text,
)

from .config import (
    DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
    DEFAULT_WORLD_ID_MAX_ATTEMPTS,
    DEFAULT_WORLD_ID_MAX_DECOMPRESSED_BYTES,
    DEFAULT_WORLD_ID_MAX_REQUEST_BYTES,
    DEFAULT_WORLD_ID_MAX_RESPONSE_BYTES,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    WORLD_ID_ENDPOINT_POLICY,
    WorldIdConfig,
    WorldIdConfigError,
    validate_verify_base_url,
    validate_world_id_resolved_addresses,
)
from .idkit import redact_world_id_payload


class WorldIdVerificationError(RuntimeError):
    """Raised when Developer Portal proof verification fails operationally."""


WorldIdRequestJson = Callable[
    [str, str, Mapping[str, Any], Mapping[str, str], float],
    Mapping[str, Any],
]

WorldIdAddressResolver = Callable[[str, int], Sequence[str]]
WorldIdUrlOpen = Callable[..., Any]


@dataclass(frozen=True)
class WorldIdTransportLimits:
    """Finite budgets for the World ID verification transport."""

    max_request_bytes: int = DEFAULT_WORLD_ID_MAX_REQUEST_BYTES
    max_response_bytes: int = DEFAULT_WORLD_ID_MAX_RESPONSE_BYTES
    max_decompressed_bytes: int = DEFAULT_WORLD_ID_MAX_DECOMPRESSED_BYTES
    max_attempts: int = DEFAULT_WORLD_ID_MAX_ATTEMPTS
    request_timeout_seconds: float = DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for name in (
            "max_request_bytes",
            "max_response_bytes",
            "max_decompressed_bytes",
            "max_attempts",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WorldIdVerificationError(f"{name} must be a positive integer")
        timeout = float(self.request_timeout_seconds)
        if timeout <= 0:
            raise WorldIdVerificationError("request_timeout_seconds must be positive")
        object.__setattr__(self, "request_timeout_seconds", timeout)


@dataclass(frozen=True)
class WorldIdVerificationResult:
    """Normalized response from World Developer Portal verification.

    Raw identity values (nullifier, nested results, raw portal response) are
    excluded from ``repr``/``str`` and from public serialization.  Callers that
    need the nullifier for private binding logic may still read ``.nullifier``.
    """

    success: bool
    action: str = ""
    nullifier: str = field(default="", repr=False)
    created_at: str = ""
    environment: str = ""
    session_id: str = field(default="", repr=False)
    message: str = ""
    results: tuple[Mapping[str, Any], ...] = field(default_factory=tuple, repr=False)
    raw_response: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def successful_results(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(result for result in self.results if bool(result.get("success")))

    @property
    def has_nullifier(self) -> bool:
        return bool(self.nullifier)

    def __repr__(self) -> str:
        return (
            f"WorldIdVerificationResult(success={self.success!r}, "
            f"action={self.action!r}, has_nullifier={self.has_nullifier!r}, "
            f"created_at={self.created_at!r}, environment={self.environment!r}, "
            f"has_session_id={bool(self.session_id)!r}, message={self.message!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def public_dict(self) -> dict[str, object]:
        """Return a browser/log-safe view without raw nullifier material."""

        return {
            "success": self.success,
            "action": self.action,
            "has_nullifier": self.has_nullifier,
            "created_at": self.created_at,
            "environment": self.environment,
            "has_session_id": bool(self.session_id),
            "message": self.message,
            "results": [redact_world_id_payload(dict(result)) for result in self.results],
        }

    def to_dict(self) -> dict[str, object]:
        """Durable/public serialization; never includes a raw nullifier."""

        return self.public_dict()


def build_world_id_request_json(
    *,
    endpoint_policy: EndpointPolicy | None = None,
    address_resolver: WorldIdAddressResolver | None = None,
    urlopen: WorldIdUrlOpen | None = None,
    limits: WorldIdTransportLimits | None = None,
) -> WorldIdRequestJson:
    """Build a bounded default transport with optional injected I/O seams."""

    policy = endpoint_policy or WORLD_ID_ENDPOINT_POLICY
    resolver = address_resolver or _system_resolve_addresses
    opener = urlopen or _bounded_urlopen
    transport_limits = limits or WorldIdTransportLimits()

    def _request_json(
        method: str,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        return _bounded_world_id_request_json(
            method,
            url,
            payload,
            headers,
            timeout_seconds,
            endpoint_policy=policy,
            address_resolver=resolver,
            urlopen=opener,
            limits=transport_limits,
        )

    return _request_json


def verify_world_id_proof(
    rp_id: str,
    idkit_payload: Mapping[str, Any],
    *,
    verify_base_url: str = DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    timeout_seconds: float = DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
    request_json: WorldIdRequestJson | None = None,
    max_request_bytes: int = DEFAULT_WORLD_ID_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_WORLD_ID_MAX_RESPONSE_BYTES,
    max_decompressed_bytes: int = DEFAULT_WORLD_ID_MAX_DECOMPRESSED_BYTES,
    max_attempts: int = DEFAULT_WORLD_ID_MAX_ATTEMPTS,
) -> WorldIdVerificationResult:
    """Verify an IDKit result with the World Developer Portal."""

    resolved_rp_id = str(rp_id or "").strip()
    if not resolved_rp_id:
        raise WorldIdVerificationError("rp_id is required")
    base_url = _validate_base_url(verify_base_url)
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise WorldIdVerificationError("timeout_seconds must be positive")
    url = f"{base_url}/api/v4/verify/{urllib_parse.quote(resolved_rp_id, safe='')}"
    limits = WorldIdTransportLimits(
        max_request_bytes=max_request_bytes,
        max_response_bytes=max_response_bytes,
        max_decompressed_bytes=max_decompressed_bytes,
        max_attempts=max_attempts,
        request_timeout_seconds=timeout,
    )
    requester = request_json or build_world_id_request_json(limits=limits)
    # Collect failures outside the ``except`` clause so Python does not attach
    # untrusted upstream exceptions as ``__context__`` (proof/nullifier/URL leak).
    failure: WorldIdVerificationError | None = None
    response: Mapping[str, Any] | None = None
    try:
        response = requester(
            "POST",
            url,
            idkit_payload,
            {"content-type": "application/json"},
            timeout,
        )
    except WorldIdVerificationError as exc:
        failure = WorldIdVerificationError(_safe_error_message(str(exc)))
    except Exception as exc:
        failure = WorldIdVerificationError(
            f"World ID verification request failed: {_safe_error_message(exc)}"
        )
    if failure is not None:
        raise failure
    assert response is not None
    return normalize_world_id_verification_response(response, idkit_payload=idkit_payload)


def verify_world_id_proof_from_config(
    config: WorldIdConfig,
    idkit_payload: Mapping[str, Any],
    *,
    request_json: WorldIdRequestJson | None = None,
) -> WorldIdVerificationResult:
    """Verify an IDKit result using a validated World ID config."""

    if not config.enabled:
        raise WorldIdVerificationError("World ID is disabled")
    return verify_world_id_proof(
        config.rp_id,
        idkit_payload,
        verify_base_url=config.verify_base_url,
        timeout_seconds=config.http_timeout_seconds,
        request_json=request_json,
        max_request_bytes=config.max_request_bytes,
        max_response_bytes=config.max_response_bytes,
        max_decompressed_bytes=config.max_decompressed_bytes,
        max_attempts=config.max_attempts,
    )


def normalize_world_id_verification_response(
    response: Mapping[str, Any],
    *,
    idkit_payload: Mapping[str, Any] | None = None,
) -> WorldIdVerificationResult:
    """Normalize a Developer Portal verification response."""

    if not isinstance(response, Mapping):
        raise WorldIdVerificationError("World ID verification response must be a JSON object")
    raw_results = response.get("results")
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise WorldIdVerificationError("World ID verification response results must be a list")
    results = tuple(result for result in raw_results if isinstance(result, Mapping))
    payload = idkit_payload or {}
    nullifier = str(response.get("nullifier") or "")
    if not nullifier:
        nullifier = next(
            (str(result.get("nullifier") or "") for result in results if result.get("nullifier")),
            "",
        )
    return WorldIdVerificationResult(
        success=bool(response.get("success")),
        action=str(response.get("action") or payload.get("action") or ""),
        nullifier=nullifier,
        created_at=str(response.get("created_at") or ""),
        environment=str(response.get("environment") or payload.get("environment") or ""),
        session_id=str(response.get("session_id") or ""),
        message=str(response.get("message") or ""),
        results=results,
        raw_response=dict(response),
    )


def _validate_base_url(value: str) -> str:
    try:
        return validate_verify_base_url(value)
    except WorldIdConfigError as exc:
        raise WorldIdVerificationError(str(exc)) from None


def _system_resolve_addresses(hostname: str, port: int) -> tuple[str, ...]:
    answers = socket.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return tuple(dict.fromkeys(answer[4][0] for answer in answers))


def _bounded_urlopen(request: urllib_request.Request, *, timeout: float) -> Any:
    """Open *request* with redirects disabled (fail-closed)."""

    opener = urllib_request.build_opener(_RejectRedirectHandler)
    return opener.open(request, timeout=timeout)


class _RejectRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Reject all HTTP redirects for World ID verification (SSRF/lateral move)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise WorldIdVerificationError(
            safe_exception_text(
                "World ID verification redirects are not allowed",
                endpoint=str(getattr(req, "full_url", "") or ""),
            )
        )


def _bounded_world_id_request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
    *,
    endpoint_policy: EndpointPolicy,
    address_resolver: WorldIdAddressResolver,
    urlopen: WorldIdUrlOpen,
    limits: WorldIdTransportLimits,
) -> Mapping[str, Any]:
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise WorldIdVerificationError("timeout_seconds must be positive")
    timeout = min(timeout, limits.request_timeout_seconds)

    try:
        endpoint_policy.validate_url(url)
    except InvalidRequestError as exc:
        raise WorldIdVerificationError(str(exc)) from None

    _validate_dns_answers(url, address_resolver)

    try:
        request_body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise WorldIdVerificationError("World ID verification payload is not JSON serializable") from None
    if len(request_body) > limits.max_request_bytes:
        raise WorldIdVerificationError(
            safe_exception_text(
                "World ID verification request exceeded its byte budget",
                endpoint=url,
            )
        )

    request_headers = {str(key): str(value) for key, value in headers.items()}
    request_headers.setdefault("content-type", "application/json")
    request_headers.setdefault("accept", "application/json")
    # Prefer identity encoding so decompression bounds stay under our control.
    request_headers.setdefault("accept-encoding", "identity")

    last_error: WorldIdVerificationError | None = None
    for attempt in range(1, limits.max_attempts + 1):
        req = urllib_request.Request(
            url,
            data=request_body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=timeout) as response:
                status = int(getattr(response, "status", None) or getattr(response, "code", 0) or 0)
                if 300 <= status < 400:
                    raise WorldIdVerificationError(
                        safe_exception_text(
                            "World ID verification redirects are not allowed",
                            endpoint=url,
                        )
                    )
                header_map = _response_headers(response)
                raw = _read_bounded_body(response, limits.max_response_bytes, endpoint=url)
                body = _maybe_decompress_body(
                    raw,
                    header_map,
                    max_decompressed_bytes=limits.max_decompressed_bytes,
                    endpoint=url,
                )
        except WorldIdVerificationError as exc:
            last_error = exc
            if attempt >= limits.max_attempts:
                raise
            continue
        except urllib_error.HTTPError as exc:
            status = int(exc.code or 0)
            if 300 <= status < 400:
                raise WorldIdVerificationError(
                    safe_exception_text(
                        "World ID verification redirects are not allowed",
                        endpoint=url,
                    )
                ) from None
            # Do not read or echo error bodies: they may contain proof material.
            raise WorldIdVerificationError(
                safe_exception_text(
                    f"World ID verification request failed with status {status}",
                    endpoint=url,
                )
            ) from None
        except (TimeoutError, socket.timeout):
            last_error = WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification request timed out",
                    endpoint=url,
                )
            )
            if attempt >= limits.max_attempts:
                raise last_error from None
            continue
        except (ConnectionError, OSError):
            last_error = WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification connection failed",
                    endpoint=url,
                )
            )
            if attempt >= limits.max_attempts:
                raise last_error from None
            continue
        except Exception:
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification request failed",
                    endpoint=url,
                )
            ) from None

        try:
            parsed = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response was not valid JSON",
                    endpoint=url,
                )
            ) from None
        if not isinstance(parsed, Mapping):
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response must be a JSON object",
                    endpoint=url,
                )
            )
        return parsed

    assert last_error is not None
    raise last_error from None


def _validate_dns_answers(url: str, address_resolver: WorldIdAddressResolver) -> None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise WorldIdVerificationError("provider endpoint hostname is required")
    # Literal IPs are already checked by EndpointPolicy.validate_url.
    try:
        socket.inet_pton(socket.AF_INET, hostname)
        return
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, hostname)
        return
    except OSError:
        pass

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = tuple(address_resolver(hostname, port))
    except WorldIdVerificationError:
        raise
    except Exception:
        raise WorldIdVerificationError(
            safe_exception_text("World ID verification DNS resolution failed", endpoint=url)
        ) from None
    try:
        validate_world_id_resolved_addresses(url, addresses)
    except WorldIdConfigError as exc:
        raise WorldIdVerificationError(str(exc)) from None


def _response_headers(response: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw_headers = getattr(response, "headers", None)
    if raw_headers is None:
        return headers
    try:
        items = raw_headers.items()
    except Exception:
        return headers
    for key, value in items:
        headers[str(key).lower()] = str(value)
    return headers


def _read_bounded_body(response: Any, max_bytes: int, *, endpoint: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response exceeded its byte budget",
                    endpoint=endpoint,
                )
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _maybe_decompress_body(
    body: bytes,
    headers: Mapping[str, str],
    *,
    max_decompressed_bytes: int,
    endpoint: str,
) -> bytes:
    encoding = (headers.get("content-encoding") or "identity").strip().lower()
    if not encoding or encoding == "identity":
        if len(body) > max_decompressed_bytes:
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response exceeded its decompression budget",
                    endpoint=endpoint,
                )
            )
        return body
    if encoding in {"gzip", "x-gzip"}:
        return _decompress_gzip(body, max_decompressed_bytes=max_decompressed_bytes, endpoint=endpoint)
    if encoding == "deflate":
        return _decompress_deflate(body, max_decompressed_bytes=max_decompressed_bytes, endpoint=endpoint)
    raise WorldIdVerificationError(
        safe_exception_text(
            "World ID verification response content-encoding is not allowed",
            endpoint=endpoint,
        )
    )


def _decompress_gzip(body: bytes, *, max_decompressed_bytes: int, endpoint: str) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as handle:
            return _read_stream_bounded(
                handle,
                max_decompressed_bytes,
                endpoint=endpoint,
            )
    except WorldIdVerificationError:
        raise
    except Exception:
        raise WorldIdVerificationError(
            safe_exception_text(
                "World ID verification response decompression failed",
                endpoint=endpoint,
            )
        ) from None


def _decompress_deflate(body: bytes, *, max_decompressed_bytes: int, endpoint: str) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        output = decompressor.decompress(body, max_decompressed_bytes + 1)
        if len(output) > max_decompressed_bytes or decompressor.unconsumed_tail:
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response exceeded its decompression budget",
                    endpoint=endpoint,
                )
            )
        # Ensure stream is complete without allowing further expansion.
        tail = decompressor.flush()
        if tail:
            if len(output) + len(tail) > max_decompressed_bytes:
                raise WorldIdVerificationError(
                    safe_exception_text(
                        "World ID verification response exceeded its decompression budget",
                        endpoint=endpoint,
                    )
                )
            output += tail
        return output
    except WorldIdVerificationError:
        raise
    except Exception:
        raise WorldIdVerificationError(
            safe_exception_text(
                "World ID verification response decompression failed",
                endpoint=endpoint,
            )
        ) from None


def _read_stream_bounded(stream: Any, max_bytes: int, *, endpoint: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise WorldIdVerificationError(
                safe_exception_text(
                    "World ID verification response exceeded its decompression budget",
                    endpoint=endpoint,
                )
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _default_world_id_request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Default transport entrypoint used when no ``request_json`` is injected."""

    return build_world_id_request_json()(
        method,
        url,
        payload,
        headers,
        timeout_seconds,
    )


def _safe_error_message(exc: object, *, limit: int = 200) -> str:
    """Return a log-safe error fragment that never echoes identity material."""

    text = str(exc or "")
    lowered = text.lower()
    for marker in (
        "proof",
        "nullifier",
        "session_nullifier",
        "merkle_root",
        "signal_hash",
        "jwt",
        "authorization",
        "bearer ",
    ):
        if marker in lowered:
            return "[redacted World ID verification error]"
    # Strip absolute URLs so endpoint material cannot leak via exception text.
    if "://" in text or "http" in lowered:
        return "[redacted World ID verification error]"
    return text[:limit]


__all__ = [
    "WorldIdAddressResolver",
    "WorldIdRequestJson",
    "WorldIdTransportLimits",
    "WorldIdUrlOpen",
    "WorldIdVerificationError",
    "WorldIdVerificationResult",
    "build_world_id_request_json",
    "normalize_world_id_verification_response",
    "verify_world_id_proof",
    "verify_world_id_proof_from_config",
]
