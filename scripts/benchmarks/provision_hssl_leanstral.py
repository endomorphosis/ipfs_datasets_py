#!/usr/bin/env python3
"""Verify and receipt the existing shared Leanstral model service.

This command is deliberately attach-only.  It never installs a model, starts a
server, or mutates model-manager state.  It verifies the canonical lock against
bounded health, served-model, model-manager, MCP, optional P2P, and non-corpus
draft observations, then writes a secret-free content-addressed receipt.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping
import urllib.error
import urllib.parse
import urllib.request


LOCK_SCHEMA: Final = "ipfs-accelerate.hssl-leanstral-runtime-lock.v1"
RECEIPT_SCHEMA: Final = "ipfs-accelerate.hssl-leanstral-health-receipt.v1"
EVIDENCE_SYMBOL: Final = "HSSLEV1126C73"
TASK_ID: Final = "HSSL-BENCH-033"
DEFAULT_LOCK_PATH: Final = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "logic_pipeline"
    / "runtime_env"
    / "leanstral.lock"
)

PINNED_IDENTITY: Final = {
    "endpoint": "http://127.0.0.1:8080/v1",
    "provider": "leanstral_local",
    "model": "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4",
    "service": "leanstral-119b-shared",
    "server_build": "llama.cpp",
}
PINNED_P2P_PORT: Final = 19001
PINNED_DRAFT_TIMEOUT_SECONDS: Final = 30.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = ("api_key", "apikey", "authorization", "credential", "password", "secret", "token")
_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_LOCAL_IPFS_ACCELERATE_SOURCE: Final = _REPOSITORY_ROOT / "ipfs_accelerate_py"


def HSSLEV1126C73() -> str:
    """Stable AST evidence marker for the shared Leanstral runtime identity."""

    return "shared Leanstral endpoint and model identity are health-verified and pinned"


class LeanstralProvisioningError(RuntimeError):
    """The shared service or its locked identity failed closed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LeanstralProvisioningError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(value: object) -> str:
    """Return a deterministic SHA-256 over canonical JSON."""

    return hashlib.sha256(_json_bytes(value)).hexdigest()


def sanitize_endpoint(endpoint: str) -> str:
    """Remove userinfo, query, and fragment data before persistence."""

    parsed = urllib.parse.urlsplit(str(endpoint).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LeanstralProvisioningError("identity.endpoint must be an HTTP(S) URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise LeanstralProvisioningError("identity.endpoint has an invalid port") from exc
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path.rstrip("/") or ""
    return urllib.parse.urlunsplit((parsed.scheme, netloc, path, "", ""))


def _mapping(value: object, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LeanstralProvisioningError(f"{name} must be an object")
    unknown = set(value) - keys
    missing = keys - set(value)
    if unknown or missing:
        raise LeanstralProvisioningError(
            f"{name} fields differ (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return value


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeanstralProvisioningError(f"{name} must be a nonempty string")
    return value.strip()


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise LeanstralProvisioningError(f"{name} must be positive")
    return float(value)


@dataclass(frozen=True)
class LeanstralRuntimeLock:
    """Validated immutable view of the canonical runtime lock."""

    document: Mapping[str, Any]
    identity: Mapping[str, str]
    http: Mapping[str, Any]
    mcp: Mapping[str, str]
    p2p: Mapping[str, Any]
    smoke: Mapping[str, Any]
    lock_sha256: str


def load_lock(path: Path | str = DEFAULT_LOCK_PATH) -> LeanstralRuntimeLock:
    """Strictly load and validate the one accepted Leanstral runtime identity."""

    lock_path = Path(path)
    try:
        raw = lock_path.read_text(encoding="utf-8")
        document = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except LeanstralProvisioningError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LeanstralProvisioningError(f"cannot load Leanstral lock: {exc}") from exc

    root = _mapping(
        document,
        "lock",
        {"schema_version", "evidence", "task_id", "identity", "http", "mcp", "p2p", "smoke"},
    )
    if root["schema_version"] != LOCK_SCHEMA:
        raise LeanstralProvisioningError("unsupported lock schema_version")
    if root["evidence"] != EVIDENCE_SYMBOL or root["task_id"] != TASK_ID:
        raise LeanstralProvisioningError("lock evidence/task identity mismatch")

    identity = _mapping(
        root["identity"],
        "identity",
        {"endpoint", "provider", "model", "service", "server_build"},
    )
    normalized_identity = {key: _nonempty(value, f"identity.{key}") for key, value in identity.items()}
    raw_endpoint = normalized_identity["endpoint"]
    normalized_identity["endpoint"] = sanitize_endpoint(raw_endpoint)
    if raw_endpoint != normalized_identity["endpoint"]:
        raise LeanstralProvisioningError(
            "identity.endpoint must not contain userinfo, query, or fragment data"
        )
    if normalized_identity != PINNED_IDENTITY:
        raise LeanstralProvisioningError("lock identity differs from the HSSL-G112 pin")

    http = _mapping(
        root["http"],
        "http",
        {"health_path", "models_path", "timeout_seconds", "max_response_bytes", "max_draft_bytes"},
    )
    for key in ("health_path", "models_path"):
        path_value = _nonempty(http[key], f"http.{key}")
        if not path_value.startswith("/") or "?" in path_value or "#" in path_value:
            raise LeanstralProvisioningError(f"http.{key} must be an absolute secret-free path")
    timeout = _positive_number(http["timeout_seconds"], "http.timeout_seconds")
    if timeout > 30:
        raise LeanstralProvisioningError("http.timeout_seconds exceeds the 30 second bound")
    for key in ("max_response_bytes", "max_draft_bytes"):
        value = _positive_number(http[key], f"http.{key}")
        if not float(value).is_integer() or value > 4 * 1024 * 1024:
            raise LeanstralProvisioningError(f"http.{key} is not a bounded byte count")

    mcp = _mapping(root["mcp"], "mcp", {"service", "list_tool", "get_tool"})
    normalized_mcp = {key: _nonempty(value, f"mcp.{key}") for key, value in mcp.items()}
    if normalized_mcp != {
        "service": "ipfs-accelerate-mcp",
        "list_tool": "model_list_served",
        "get_tool": "model_get_served",
    }:
        raise LeanstralProvisioningError("MCP discovery identity differs from the pin")

    p2p = _mapping(root["p2p"], "p2p", {"enabled", "required_provider", "custom_port"})
    if not isinstance(p2p["enabled"], bool):
        raise LeanstralProvisioningError("p2p.enabled must be boolean")
    if _nonempty(p2p["required_provider"], "p2p.required_provider") != PINNED_IDENTITY["provider"]:
        raise LeanstralProvisioningError("p2p.required_provider may not substitute another provider")
    port = p2p["custom_port"]
    if isinstance(port, bool) or not isinstance(port, int) or port != PINNED_P2P_PORT:
        raise LeanstralProvisioningError("p2p.custom_port differs from the configured pin")

    smoke = _mapping(
        root["smoke"],
        "smoke",
        {"prompt", "max_tokens", "temperature", "uses_benchmark_inputs"},
    )
    prompt = _nonempty(smoke["prompt"], "smoke.prompt")
    if len(prompt.encode("utf-8")) > 1024:
        raise LeanstralProvisioningError("smoke.prompt exceeds 1024 bytes")
    if smoke["uses_benchmark_inputs"] is not False:
        raise LeanstralProvisioningError("smoke probe must not use benchmark inputs")
    max_tokens = smoke["max_tokens"]
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 128:
        raise LeanstralProvisioningError("smoke.max_tokens must be between 1 and 128")
    temperature = smoke["temperature"]
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 1:
        raise LeanstralProvisioningError("smoke.temperature must be between 0 and 1")

    canonical_document = json.loads(_json_bytes(root))
    return LeanstralRuntimeLock(
        document=MappingProxyType(canonical_document),
        identity=MappingProxyType(dict(normalized_identity)),
        http=MappingProxyType(dict(http)),
        mcp=MappingProxyType(normalized_mcp),
        p2p=MappingProxyType(dict(p2p)),
        smoke=MappingProxyType(dict(smoke)),
        lock_sha256=semantic_sha256(canonical_document),
    )


def _origin_url(endpoint: str, path: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _endpoint_url(endpoint: str, path: str) -> str:
    if path.startswith("/v1/"):
        return _origin_url(endpoint, path)
    if path == "/health":
        return _origin_url(endpoint, path)
    return endpoint.rstrip("/") + "/" + path.lstrip("/")


def _bounded_read(response: Any, limit: int) -> bytes:
    try:
        content_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if content_length is not None and int(content_length) > limit:
            raise LeanstralProvisioningError("HTTP response exceeds configured byte bound")
    except (TypeError, ValueError):
        pass
    try:
        body = response.read(limit + 1)
    except TypeError:
        body = response.read()
    if not isinstance(body, (bytes, bytearray)) or len(body) > limit:
        raise LeanstralProvisioningError("HTTP response exceeds configured byte bound")
    return bytes(body)


def _http_json(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    payload: Mapping[str, Any] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[dict[str, Any], Mapping[str, str]]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        data = _json_bytes(payload)
        headers["Content-Type"] = "application/json"
        method = "POST"
        api_key = os.environ.get("HSSL_LEANSTRAL_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener(request, timeout=timeout) as response:
            body = _bounded_read(response, max_bytes)
            response_headers = {
                str(key).lower(): str(value)
                for key, value in getattr(response, "headers", {}).items()
                if str(key).lower() in {"server", "x-service-id", "x-model-provider"}
            }
    except LeanstralProvisioningError:
        raise
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise LeanstralProvisioningError(f"bounded request failed for {sanitize_endpoint(url)}: {exc}") from exc
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LeanstralProvisioningError("service returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LeanstralProvisioningError("service JSON response must be an object")
    return value, MappingProxyType(response_headers)


def _models(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("data", payload.get("models"))
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        raise LeanstralProvisioningError("model-list response is missing a model array")
    result: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, str):
            record = {"id": record}
        if isinstance(record, dict):
            result.append(record)
    return result


def _identity_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _assert_model_identity(lock: LeanstralRuntimeLock, record: Mapping[str, Any], surface: str) -> dict[str, Any]:
    """Bind one discovery record to the locked logical and transport identity.

    llama.cpp's native model list reports ``owned_by=llamacpp`` and does not
    know the supervisor's logical provider/service aliases.  ModelManager and
    its MCP tool deliberately preserve that transport provider.  Treat those
    fields as a server-build attestation while still rejecting any unrelated
    provider, endpoint, service, build, or model substitution.
    """

    model = str(record.get("id") or record.get("model_id") or record.get("model") or "")
    provider = str(record.get("provider") or record.get("owned_by") or "")
    metadata = record.get("metadata", record.get("meta", {}))
    metadata = metadata if isinstance(metadata, dict) else {}
    service = str(record.get("service") or metadata.get("service_id") or "")
    server_build = str(record.get("server_build") or metadata.get("server_build") or "")
    endpoint = record.get("endpoint")
    expected = lock.identity
    mismatches = []
    if model != expected["model"]:
        mismatches.append("model")
    if provider and (
        provider != expected["provider"]
        and _identity_token(provider) != _identity_token(expected["server_build"])
    ):
        mismatches.append("provider")
    if service and service != expected["service"]:
        mismatches.append("service")
    if (
        server_build
        and _identity_token(server_build)
        != _identity_token(expected["server_build"])
    ):
        mismatches.append("server_build")
    if endpoint is not None and sanitize_endpoint(str(endpoint)) != expected["endpoint"]:
        mismatches.append("endpoint")
    if surface in {"model manager", "MCP"} and endpoint is None:
        mismatches.append("endpoint")
    if "status" in record and str(record["status"]).casefold() != "available":
        mismatches.append("status")
    if "served" in record and record["served"] is not True:
        mismatches.append("served")
    if mismatches:
        raise LeanstralProvisioningError(
            f"{surface} identity mismatch: {', '.join(sorted(set(mismatches)))}"
        )
    return dict(expected)


def verify_proof_draft(
    lock: LeanstralRuntimeLock,
    draft: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate identity and force every model draft to remain non-authoritative."""

    for key in ("provider", "model", "service"):
        if str(draft.get(key) or "") != lock.identity[key]:
            raise LeanstralProvisioningError(f"proof draft {key} identity mismatch")
    text = draft.get("draft_text")
    if not isinstance(text, str) or not text.strip():
        raise LeanstralProvisioningError("proof draft text is empty")
    if len(text.encode("utf-8")) > int(lock.http["max_draft_bytes"]):
        raise LeanstralProvisioningError("proof draft exceeds configured byte bound")
    if draft.get("assurance") != "unverified":
        raise LeanstralProvisioningError("proof draft assurance must be unverified")
    for claim in ("verified", "authoritative", "kernel_checked"):
        if draft.get(claim) is not False:
            raise LeanstralProvisioningError(f"proof draft {claim} must remain false")
    return {
        "provider": lock.identity["provider"],
        "model": lock.identity["model"],
        "service": lock.identity["service"],
        "draft_text": text.strip(),
        "draft_sha256": hashlib.sha256(text.strip().encode("utf-8")).hexdigest(),
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
        "kernel_receipt_sha256": None,
    }


def verify_p2p_evidence(
    lock: LeanstralRuntimeLock,
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate configured P2P advertisements and dial results, if requested."""

    if not lock.p2p["enabled"]:
        if evidence not in (None, {}):
            raise LeanstralProvisioningError("P2P evidence supplied while locked transport is disabled")
        return {
            "enabled": False,
            "provider": lock.p2p["required_provider"],
            "custom_port": lock.p2p["custom_port"],
        }
    if not isinstance(evidence, Mapping):
        raise LeanstralProvisioningError("configured P2P provider requires transport evidence")
    if evidence.get("provider") != lock.identity["provider"]:
        raise LeanstralProvisioningError("P2P evidence substituted another provider")
    advertised = evidence.get("advertised_addrs")
    dialed = evidence.get("dialed_addrs")
    if not isinstance(advertised, list) or not isinstance(dialed, list) or not advertised or not dialed:
        raise LeanstralProvisioningError("P2P evidence requires advertised and dialed addresses")

    def validate_addr(value: object, *, dial: bool) -> str:
        if not isinstance(value, str):
            raise LeanstralProvisioningError("P2P address must be a string")
        match = re.fullmatch(r"/ip4/([^/]+)/tcp/([0-9]+)(?:/p2p/[^/]+)?", value)
        if not match or int(match.group(2)) != int(lock.p2p["custom_port"]):
            raise LeanstralProvisioningError("P2P address does not use the configured custom port")
        host = match.group(1)
        if host == "0.0.0.0" or host.startswith("127."):
            raise LeanstralProvisioningError("P2P address is not policy-approved and dialable")
        return value

    if evidence.get("dial_succeeded") is not True:
        raise LeanstralProvisioningError("P2P evidence does not prove a successful dial")
    return {
        "enabled": True,
        "provider": lock.identity["provider"],
        "custom_port": lock.p2p["custom_port"],
        "advertised_addrs": [validate_addr(item, dial=False) for item in advertised],
        "dialed_addrs": [validate_addr(item, dial=True) for item in dialed],
        "dial_succeeded": True,
    }


def _default_model_manager_probe(lock: LeanstralRuntimeLock) -> list[dict[str, Any]]:
    source = str(_LOCAL_IPFS_ACCELERATE_SOURCE)
    if (
        (_LOCAL_IPFS_ACCELERATE_SOURCE / "ipfs_accelerate_py").is_dir()
        and source not in sys.path
    ):
        sys.path.insert(0, source)
    try:
        from ipfs_accelerate_py.model_manager import ModelManager
    except ImportError as exc:
        raise LeanstralProvisioningError("model-manager discovery is unavailable") from exc
    with tempfile.TemporaryDirectory(prefix="hssl-leanstral-model-manager-") as state_dir:
        manager = ModelManager(
            storage_path=str(Path(state_dir) / "models.json"),
            use_database=False,
            enable_ipfs=False,
        )
        try:
            return manager.list_served_models(
                endpoint_url=lock.identity["endpoint"],
                timeout=float(lock.http["timeout_seconds"]),
            )
        finally:
            close = getattr(manager, "close", None)
            if callable(close):
                close()


def _default_mcp_probe(lock: LeanstralRuntimeLock) -> list[dict[str, Any]]:
    source = str(_LOCAL_IPFS_ACCELERATE_SOURCE)
    if (
        (_LOCAL_IPFS_ACCELERATE_SOURCE / "ipfs_accelerate_py").is_dir()
        and source not in sys.path
    ):
        sys.path.insert(0, source)
    try:
        import anyio
        import ipfs_accelerate_py.model_manager as manager_module
        from ipfs_accelerate_py.model_manager import ModelManager
        from ipfs_accelerate_py.mcp_server.tools.model_tools.native_model_tools import model_list_served
    except ImportError as exc:
        raise LeanstralProvisioningError("MCP model discovery is unavailable") from exc

    async def call() -> dict[str, Any]:
        return await model_list_served(
            endpoint_url=lock.identity["endpoint"],
            timeout=float(lock.http["timeout_seconds"]),
        )

    with tempfile.TemporaryDirectory(prefix="hssl-leanstral-mcp-manager-") as state_dir:
        manager = ModelManager(
            storage_path=str(Path(state_dir) / "models.json"),
            use_database=False,
            enable_ipfs=False,
        )
        original_get_default = manager_module.get_default_model_manager
        manager_module.get_default_model_manager = lambda: manager
        try:
            result = anyio.run(call)
        finally:
            manager_module.get_default_model_manager = original_get_default
            close = getattr(manager, "close", None)
            if callable(close):
                close()
    if result.get("status") != "success" or not isinstance(result.get("models"), list):
        raise LeanstralProvisioningError("MCP model discovery failed")
    return result["models"]


def _call_probe(probe: Callable[..., Any], lock: LeanstralRuntimeLock) -> Any:
    try:
        parameters = inspect.signature(probe).parameters
    except (TypeError, ValueError):
        parameters = {"lock": object()}
    return probe(lock) if parameters else probe()


def provision_shared_leanstral(
    lock: LeanstralRuntimeLock,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    model_manager_probe: Callable[..., Any] = _default_model_manager_probe,
    mcp_probe: Callable[..., Any] = _default_mcp_probe,
    p2p_evidence: Mapping[str, Any] | None = None,
    draft_probe: bool = True,
    draft_timeout_seconds: float = PINNED_DRAFT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Verify all shared-service discovery surfaces and return a safe receipt."""

    timeout = float(lock.http["timeout_seconds"])
    if (
        isinstance(draft_timeout_seconds, bool)
        or not 1.0 <= float(draft_timeout_seconds) <= 60.0
    ):
        raise LeanstralProvisioningError(
            "draft timeout must be between one and sixty seconds"
        )
    response_limit = int(lock.http["max_response_bytes"])
    health, health_headers = _http_json(
        _endpoint_url(lock.identity["endpoint"], str(lock.http["health_path"])),
        timeout=timeout,
        max_bytes=response_limit,
        opener=opener,
    )
    if str(health.get("status", "")).lower() not in {"ok", "healthy"}:
        raise LeanstralProvisioningError("shared Leanstral health status is not healthy")

    models_payload, _model_headers = _http_json(
        _endpoint_url(lock.identity["endpoint"], str(lock.http["models_path"])),
        timeout=timeout,
        max_bytes=response_limit,
        opener=opener,
    )
    matching = [
        _assert_model_identity(lock, record, "HTTP model list")
        for record in _models(models_payload)
        if str(record.get("id") or record.get("model") or record.get("model_id") or "")
        == lock.identity["model"]
    ]
    if len(matching) != 1:
        raise LeanstralProvisioningError("HTTP model list must advertise exactly one pinned model")

    manager_records = _call_probe(model_manager_probe, lock)
    mcp_records = _call_probe(mcp_probe, lock)
    if not isinstance(manager_records, list) or not isinstance(mcp_records, list):
        raise LeanstralProvisioningError("model-manager and MCP probes must return model lists")

    def one(records: list[Any], surface: str) -> dict[str, Any]:
        accepted = [
            _assert_model_identity(lock, record, surface)
            for record in records
            if isinstance(record, Mapping)
            and str(record.get("id") or record.get("model") or record.get("model_id") or "")
            == lock.identity["model"]
        ]
        if len(accepted) != 1:
            raise LeanstralProvisioningError(f"{surface} must advertise exactly one pinned model")
        return accepted[0]

    p2p = verify_p2p_evidence(lock, p2p_evidence)
    draft_receipt: dict[str, Any] | None = None
    if draft_probe:
        completion, _completion_headers = _http_json(
            _endpoint_url(lock.identity["endpoint"], "/v1/chat/completions"),
            timeout=float(draft_timeout_seconds),
            max_bytes=response_limit,
            payload={
                "model": lock.identity["model"],
                "messages": [{"role": "user", "content": lock.smoke["prompt"]}],
                "max_tokens": lock.smoke["max_tokens"],
                "temperature": lock.smoke["temperature"],
                "stream": False,
            },
            opener=opener,
        )
        choices = completion.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        completion_model = str(completion.get("model") or lock.identity["model"])
        draft_receipt = verify_proof_draft(
            lock,
            {
                "provider": lock.identity["provider"],
                "model": completion_model,
                "service": lock.identity["service"],
                "draft_text": text,
                "assurance": "unverified",
                "verified": False,
                "authoritative": False,
                "kernel_checked": False,
            },
        )
        draft_receipt.pop("draft_text", None)

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "evidence": EVIDENCE_SYMBOL,
        "task_id": TASK_ID,
        "lock_sha256": lock.lock_sha256,
        "identity": dict(lock.identity),
        "service_owner": "agent_supervisor",
        "attach_only": True,
        "duplicate_server_started": False,
        "bounded": {
            "timeout_seconds": timeout,
            "draft_timeout_seconds": float(draft_timeout_seconds),
            "max_response_bytes": response_limit,
            "max_draft_bytes": int(lock.http["max_draft_bytes"]),
        },
        "health": {
            "status": str(health["status"]).lower(),
            "server_build": str(
                health.get("server_build")
                or health_headers.get("server")
                or ""
            ),
        },
        "http_model_list": matching[0],
        "model_manager": one(manager_records, "model manager"),
        "mcp": {
            "service": lock.mcp["service"],
            "list_tool": lock.mcp["list_tool"],
            "model": one(mcp_records, "MCP"),
        },
        "p2p": p2p,
        "proof_draft": draft_receipt,
        "uses_benchmark_inputs": False,
        "secrets_serialized": False,
    }
    if receipt["health"]["server_build"] != lock.identity["server_build"]:
        raise LeanstralProvisioningError("health server build differs from the lock")
    receipt["receipt_sha256"] = semantic_sha256(receipt)
    return receipt


def validate_receipt(lock: LeanstralRuntimeLock, receipt: Mapping[str, Any]) -> None:
    """Revalidate a serialized health receipt and its content digest."""

    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise LeanstralProvisioningError("receipt schema mismatch")
    if receipt.get("lock_sha256") != lock.lock_sha256:
        raise LeanstralProvisioningError("receipt is not bound to the canonical lock")
    if receipt.get("identity") != dict(lock.identity):
        raise LeanstralProvisioningError("receipt identity mismatch")
    supplied = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    if not isinstance(supplied, str) or not _SHA256_RE.fullmatch(supplied):
        raise LeanstralProvisioningError("receipt digest is missing or malformed")
    if semantic_sha256(unsigned) != supplied:
        raise LeanstralProvisioningError("receipt digest mismatch")
    serialized = json.dumps(receipt, sort_keys=True).lower()
    if any(f'"{key}"' in serialized for key in _SECRET_KEYS):
        raise LeanstralProvisioningError("receipt contains a secret-bearing field")
    if receipt.get("attach_only") is not True or receipt.get("duplicate_server_started") is not False:
        raise LeanstralProvisioningError("receipt does not prove attach-only provisioning")
    if receipt.get("uses_benchmark_inputs") is not False or receipt.get("secrets_serialized") is not False:
        raise LeanstralProvisioningError("receipt violates input/secret safety")
    draft = receipt.get("proof_draft")
    if (
        not isinstance(draft, Mapping)
        or draft.get("verified") is not False
        or draft.get("authoritative") is not False
        or draft.get("kernel_checked") is not False
        or draft.get("kernel_receipt_sha256") is not None
    ):
        raise LeanstralProvisioningError(
            "receipt must retain one untrusted, non-authoritative proof draft"
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LeanstralProvisioningError(f"cannot load JSON evidence: {exc}") from exc
    if not isinstance(value, dict):
        raise LeanstralProvisioningError("JSON evidence must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--receipt", type=Path, help="write the canonical health receipt")
    parser.add_argument("--p2p-evidence", type=Path, help="configured transport evidence JSON")
    parser.add_argument(
        "--skip-draft",
        action="store_true",
        help="health-only diagnostics; receipts for HSSL-G112 normally include the bounded draft",
    )
    parser.add_argument(
        "--validate-receipt",
        type=Path,
        help="validate an existing receipt without making network calls",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if args.validate_receipt:
            validate_receipt(lock, _read_json(args.validate_receipt))
            print(json.dumps({"status": "valid", "lock_sha256": lock.lock_sha256}, sort_keys=True))
            return 0
        if args.skip_draft and args.receipt:
            raise LeanstralProvisioningError(
                "--skip-draft is diagnostic-only and cannot write an HSSL-G112 receipt"
            )
        p2p = _read_json(args.p2p_evidence) if args.p2p_evidence else None
        receipt = provision_shared_leanstral(
            lock,
            p2p_evidence=p2p,
            draft_probe=not args.skip_draft,
        )
        if args.skip_draft:
            print(
                json.dumps(
                    {
                        "status": "healthy_diagnostic",
                        "lock_sha256": lock.lock_sha256,
                        "identity": dict(lock.identity),
                        "receipt_written": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        validate_receipt(lock, receipt)
        rendered = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except LeanstralProvisioningError as exc:
        print(f"Leanstral provisioning failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
