#!/usr/bin/env python3
"""Verify and receipt the existing shared Leanstral model service.

This command is deliberately attach-only.  It never installs a model, starts a
server, or mutates model-manager state.  It verifies the canonical lock against
bounded health, served-model, model-manager, MCP, optional P2P, and non-corpus
draft observations, then writes a secret-free content-addressed receipt.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from types import MappingProxyType
from typing import Any, Callable, Final, Iterator, Mapping
import urllib.error
import urllib.parse
import urllib.request

# Direct ``python scripts/...`` execution places only this script directory on
# sys.path.  Add the resolved repository root so the shared benchmark CID
# bridge is used in both CLI and imported-test modes.
_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.logic_pipeline.source_bound_import import (
    SourceBoundImportError,
    import_source_bound_ipfs_accelerate,
)


LOCK_SCHEMA: Final = "ipfs-accelerate.hssl-leanstral-runtime-lock.v2"
RECEIPT_SCHEMA: Final = "ipfs-accelerate.hssl-leanstral-health-receipt.v2"
EVIDENCE_SYMBOL: Final = "HSSLEV1126C73"
TASK_ID: Final = "HSSL-BENCH-033"
TOPOLOGY_TASK_ID: Final = "HSSL-G203"
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
PINNED_P2P_LISTEN_ADDRS: Final = ("/ip4/0.0.0.0/tcp/19001",)
PINNED_P2P_INTERFACES: Final = ("wlP9s9", "tun0", "tun1")
PINNED_P2P_IPV4: Final = ("172.30.4.2", "10.8.0.99", "10.10.0.14")
PINNED_P2P_BOOTSTRAP_PEERS: Final = (
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
)
PINNED_P2P_RENDEZVOUS: Final = {
    "mode": "same_as_service_peer",
    "namespace": "leanstral-local",
}
PINNED_P2P_CAPABILITIES: Final = {
    "bootstrap": True,
    "floodsub": False,
    "mcp_stream": True,
    "pubsub": False,
    "rendezvous": True,
}
PINNED_DRAFT_TIMEOUT_SECONDS: Final = 30.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = ("api_key", "apikey", "authorization", "credential", "password", "secret", "token")
_SOURCE_IMPORT_LOCK = threading.RLock()


def _lock_binding_policy() -> dict[str, Any]:
    """Return a fresh JSON policy document for the v2 lock identity."""

    return {
        "authoritative_field": "lock_cid",
        "cid_codec": "dag-json",
        "cid_version": 1,
        "multibase": "base32",
        "multihash": "sha2-256",
        "legacy_compatibility_fields": ["lock_sha256"],
    }


def _receipt_binding_policy() -> dict[str, Any]:
    """Return a fresh JSON policy document for the v2 receipt identity."""

    return {
        "authoritative_field": "receipt_cid",
        "cid_codec": "dag-json",
        "cid_version": 1,
        "multibase": "base32",
        "multihash": "sha2-256",
        "legacy_compatibility_fields": ["receipt_sha256"],
        "identity_fields_excluded_from_body": [
            "receipt_cid",
            "receipt_sha256",
        ],
    }


def HSSLEV1126C73() -> str:
    """Stable AST evidence marker for the shared Leanstral runtime identity."""

    return "shared Leanstral endpoint and model identity are health-verified and pinned"


class LeanstralProvisioningError(RuntimeError):
    """The shared service or its locked identity failed closed."""


def _module_family(name: str) -> dict[str, object]:
    prefix = name + "."
    return {
        module_name: module
        for module_name, module in tuple(sys.modules.items())
        if module_name == name or module_name.startswith(prefix)
    }


def _restore_module_family(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    for module_name in after:
        if module_name not in before:
            sys.modules.pop(module_name, None)
    for module_name, module in before.items():
        sys.modules[module_name] = module  # type: ignore[assignment]

    sentinel = object()
    for module_name in sorted(
        set(before) | set(after),
        key=lambda name: name.count("."),
    ):
        parent_name, separator, child_name = module_name.rpartition(".")
        if not separator:
            continue
        parent = sys.modules.get(parent_name)
        if parent is None:
            continue
        expected = before.get(module_name, sentinel)
        if expected is not sentinel:
            setattr(parent, child_name, expected)
            continue
        observed = after.get(module_name, sentinel)
        if (
            observed is not sentinel
            and getattr(parent, child_name, sentinel) is observed
        ):
            delattr(parent, child_name)


@contextmanager
def _preserve_import_path() -> Iterator[None]:
    """Restore sibling-package provenance after local source discovery."""

    with _SOURCE_IMPORT_LOCK:
        original_path = list(sys.path)
        original_datasets_modules = _module_family("ipfs_datasets_py")
        try:
            yield
        finally:
            _restore_module_family(
                original_datasets_modules,
                _module_family("ipfs_datasets_py"),
            )
            sys.path[:] = original_path


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
    """Return the frozen G112 compatibility digest over canonical JSON.

    New v2 lock identities use ``cid_for_dag_json``.  This bare digest remains
    only for consumers of the historical ``lock_sha256`` and receipt fields.
    """

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
    lock_cid: str
    # Frozen HSSL-G112 compatibility only.  ``lock_cid`` is authoritative.
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
        {
            "schema_version",
            "evidence",
            "task_id",
            "topology_task_id",
            "identity",
            "http",
            "mcp",
            "p2p",
            "smoke",
        },
    )
    if root["schema_version"] != LOCK_SCHEMA:
        raise LeanstralProvisioningError("unsupported lock schema_version")
    if root["evidence"] != EVIDENCE_SYMBOL or root["task_id"] != TASK_ID:
        raise LeanstralProvisioningError("lock evidence/task identity mismatch")
    if root["topology_task_id"] != TOPOLOGY_TASK_ID:
        raise LeanstralProvisioningError("lock topology task identity mismatch")

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

    p2p = _mapping(
        root["p2p"],
        "p2p",
        {
            "advertise_policy",
            "bootstrap_peers",
            "capabilities",
            "custom_port",
            "enabled",
            "inference_allowed",
            "listen_addrs",
            "probe_timeout_seconds",
            "rendezvous",
            "required_provider",
            "server_instance_count",
        },
    )
    if p2p["enabled"] is not True:
        raise LeanstralProvisioningError("p2p.enabled must be true")
    if _nonempty(p2p["required_provider"], "p2p.required_provider") != PINNED_IDENTITY["provider"]:
        raise LeanstralProvisioningError("p2p.required_provider may not substitute another provider")
    port = p2p["custom_port"]
    if isinstance(port, bool) or not isinstance(port, int) or port != PINNED_P2P_PORT:
        raise LeanstralProvisioningError("p2p.custom_port differs from the configured pin")
    if tuple(p2p["listen_addrs"]) != PINNED_P2P_LISTEN_ADDRS:
        raise LeanstralProvisioningError(
            "p2p.listen_addrs must pin the wildcard listener on custom port 19001"
        )
    policy = _mapping(
        p2p["advertise_policy"],
        "p2p.advertise_policy",
        {
            "allowed_interfaces",
            "reject_container_interfaces",
            "reject_down_interfaces",
            "reject_loopback",
            "reject_unrelated_interfaces",
            "required_ipv4",
        },
    )
    if tuple(policy["allowed_interfaces"]) != PINNED_P2P_INTERFACES:
        raise LeanstralProvisioningError(
            "p2p advertise interface policy differs from the frozen host interfaces"
        )
    if set(policy["required_ipv4"]) != set(PINNED_P2P_IPV4):
        raise LeanstralProvisioningError(
            "p2p required advertised IPv4 identities differ from the pin"
        )
    for key in (
        "reject_container_interfaces",
        "reject_down_interfaces",
        "reject_loopback",
        "reject_unrelated_interfaces",
    ):
        if policy[key] is not True:
            raise LeanstralProvisioningError(f"p2p.advertise_policy.{key} must be true")
    if tuple(p2p["bootstrap_peers"]) != PINNED_P2P_BOOTSTRAP_PEERS:
        raise LeanstralProvisioningError(
            "p2p bootstrap peer identities differ from the pin"
        )
    rendezvous = _mapping(
        p2p["rendezvous"],
        "p2p.rendezvous",
        {"mode", "namespace"},
    )
    if rendezvous != PINNED_P2P_RENDEZVOUS:
        raise LeanstralProvisioningError(
            "p2p rendezvous identity differs from the service-peer pin"
        )
    capabilities = _mapping(
        p2p["capabilities"],
        "p2p.capabilities",
        set(PINNED_P2P_CAPABILITIES),
    )
    if capabilities != PINNED_P2P_CAPABILITIES:
        raise LeanstralProvisioningError(
            "p2p capabilities must truthfully disable pubsub and floodsub"
        )
    probe_timeout = _positive_number(
        p2p["probe_timeout_seconds"],
        "p2p.probe_timeout_seconds",
    )
    if probe_timeout > 10:
        raise LeanstralProvisioningError(
            "p2p.probe_timeout_seconds exceeds the 10 second bound"
        )
    if p2p["server_instance_count"] != 1:
        raise LeanstralProvisioningError(
            "p2p.server_instance_count must pin one attached server"
        )
    if p2p["inference_allowed"] is not False:
        raise LeanstralProvisioningError(
            "p2p.inference_allowed must remain false"
        )

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
        lock_cid=cid_for_dag_json(canonical_document),
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
    transport_model = str(record.get("transport_model_id") or model)
    logical_model = str(record.get("logical_model_id") or "")
    provider = str(record.get("provider") or record.get("owned_by") or "")
    metadata = record.get("metadata", record.get("meta", {}))
    metadata = metadata if isinstance(metadata, dict) else {}
    service = str(record.get("service") or metadata.get("service_id") or "")
    server_build = str(record.get("server_build") or metadata.get("server_build") or "")
    endpoint = record.get("endpoint")
    expected = lock.identity
    mismatches = []
    if transport_model != expected["model"]:
        mismatches.append("model")
    if logical_model and logical_model != expected["provider"]:
        mismatches.append("logical_model")
    if (
        surface in {"model manager", "MCP"}
        and record.get("transport_model_id") is not None
        and model != expected["provider"]
    ):
        mismatches.append("logical_model")
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
    """Validate the complete CID-bound, non-inference P2P topology receipt."""

    if not isinstance(evidence, Mapping):
        raise LeanstralProvisioningError("configured P2P provider requires transport evidence")
    if any(not isinstance(field, str) for field in evidence):
        raise LeanstralProvisioningError(
            "P2P topology evidence field names must be strings"
        )

    receipt_fields = {
        "address_selection",
        "contract",
        "observation",
        "receipt_cid",
        "schema",
        "validation",
    }
    evidence_fields = set(evidence)
    receipt_envelope = bool(evidence_fields & receipt_fields)
    topology_observation: Mapping[str, Any] = evidence
    if receipt_envelope:
        missing = sorted(receipt_fields - evidence_fields)
        unknown = sorted(evidence_fields - receipt_fields)
        if missing or unknown:
            raise LeanstralProvisioningError(
                "P2P topology receipt fields differ "
                f"(missing={missing}, unknown={unknown})"
            )
        candidate_observation = evidence.get("observation")
        if not isinstance(candidate_observation, Mapping):
            raise LeanstralProvisioningError(
                "P2P topology receipt observation must be an object"
            )
        topology_observation = candidate_observation

    with _preserve_import_path():
        try:
            topology_module = import_source_bound_ipfs_accelerate(
                "ipfs_accelerate_py.mcplusplus_module.leanstral_topology"
            )
            validate_leanstral_topology_mapping = getattr(
                topology_module,
                "validate_leanstral_topology_mapping",
            )
            canonical_json_cid = getattr(
                topology_module,
                "canonical_json_cid",
            )
            if not all(
                callable(value)
                for value in (
                    validate_leanstral_topology_mapping,
                    canonical_json_cid,
                )
            ):
                raise AttributeError("topology validator is not callable")
        except (SourceBoundImportError, AttributeError) as exc:
            raise LeanstralProvisioningError(
                "Leanstral P2P topology validator is unavailable"
            ) from exc
        try:
            validation = validate_leanstral_topology_mapping(
                topology_observation
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise LeanstralProvisioningError(
                f"P2P topology evidence is malformed: {exc}"
            ) from exc
    if not validation.valid:
        raise LeanstralProvisioningError(
            "P2P topology evidence failed: " + ", ".join(validation.errors)
        )
    if receipt_envelope:
        supplied_receipt = dict(evidence)
        supplied_cid = supplied_receipt.pop("receipt_cid")
        try:
            recomputed_cid = canonical_json_cid(supplied_receipt)
        except (TypeError, ValueError) as exc:
            raise LeanstralProvisioningError(
                "P2P topology receipt is not canonical JSON"
            ) from exc
        if (
            type(supplied_cid) is not str
            or supplied_cid != recomputed_cid
            or supplied_cid != validation.receipt_cid
            or dict(evidence) != dict(validation.receipt)
        ):
            raise LeanstralProvisioningError(
                "P2P topology receipt is not the canonical CID-bound receipt"
            )

    observation = validation.receipt["observation"]
    if tuple(observation["listen_addrs"]) != tuple(lock.p2p["listen_addrs"]):
        raise LeanstralProvisioningError("P2P evidence changed the frozen listener")
    if tuple(observation["advertise_interface_allowlist"]) != tuple(
        lock.p2p["advertise_policy"]["allowed_interfaces"]
    ):
        raise LeanstralProvisioningError(
            "P2P evidence changed the frozen advertise interface policy"
        )
    selected = set(validation.receipt["address_selection"]["selected"])
    if selected != set(lock.p2p["advertise_policy"]["required_ipv4"]):
        raise LeanstralProvisioningError(
            "P2P evidence did not advertise every frozen active local address"
        )

    bootstrap_exercises = observation["bootstrap_exercises"]
    pinned_bootstraps = set(lock.p2p["bootstrap_peers"])
    public_exercises = [
        item for item in bootstrap_exercises
        if item["target"] in pinned_bootstraps
    ]
    public_targets = {item["target"] for item in public_exercises}
    if (
        public_targets != pinned_bootstraps
        or len(public_exercises) != len(pinned_bootstraps)
    ):
        raise LeanstralProvisioningError(
            "P2P bootstrap exercises did not match every frozen public peer"
        )
    if any(
        item["observer_peer_id"] != observation["peer_id"]
        or item["attempted"] is not True
        for item in public_exercises
    ):
        raise LeanstralProvisioningError(
            "P2P public bootstrap exercise was not attempted by the service peer"
        )
    if not any(item["success"] is True for item in public_exercises):
        raise LeanstralProvisioningError(
            "P2P evidence requires at least one successful public bootstrap"
        )
    if any(
        (item["success"] is True and item["error"] is not None)
        or (
            item["success"] is False
            and item["error"] not in {"connect_failed", "timeout"}
        )
        for item in public_exercises
    ):
        raise LeanstralProvisioningError(
            "P2P public bootstrap result is inconsistent with its error"
        )

    independent_dial = observation["independent_dial"]
    independent_target = independent_dial["target_multiaddr"]
    if independent_target not in observation["advertised_multiaddrs"]:
        raise LeanstralProvisioningError(
            "P2P independent client bootstrap target was not advertised"
        )
    independent_exercises = [
        item for item in bootstrap_exercises
        if item["target"] not in pinned_bootstraps
    ]
    if any(
        item["target"] not in observation["advertised_multiaddrs"]
        for item in independent_exercises
    ):
        raise LeanstralProvisioningError(
            "P2P bootstrap exercise used an unpinned peer identity"
        )
    if len(independent_exercises) != 1:
        raise LeanstralProvisioningError(
            "P2P evidence requires exactly one independent client service bootstrap"
        )
    independent_exercise = independent_exercises[0]
    if independent_exercise["target"] != independent_target:
        raise LeanstralProvisioningError(
            "P2P independent service bootstrap did not match the direct-dial target"
        )
    if (
        independent_exercise["observer_peer_id"]
        != independent_dial["dialer_peer_id"]
        or independent_exercise["attempted"] is not True
        or independent_exercise["success"] is not True
        or independent_exercise["error"] is not None
    ):
        raise LeanstralProvisioningError(
            "P2P service bootstrap was not completed by the independent client"
        )

    for item in observation["rendezvous_exercises"]:
        if item["namespace"] != lock.p2p["rendezvous"]["namespace"]:
            raise LeanstralProvisioningError(
                "P2P rendezvous exercise changed the frozen namespace"
            )
    expected_model = {
        "id": lock.identity["provider"],
        "model_id": lock.identity["provider"],
        "logical_model_id": lock.identity["provider"],
        "transport_model_id": lock.identity["model"],
        "provider": "llamacpp",
        "transport": "llamacpp",
        "endpoint": lock.identity["endpoint"],
    }
    models = observation["served_models"]
    if len(models) != 1 or any(
        models[0].get(key) != value for key, value in expected_model.items()
    ):
        raise LeanstralProvisioningError(
            "P2P evidence changed the logical or HTTP transport model identity"
        )
    if (
        observation["server_instance_count"] != lock.p2p["server_instance_count"]
        or observation["inference_attempted"] is not lock.p2p["inference_allowed"]
    ):
        raise LeanstralProvisioningError(
            "P2P evidence violated the single-server/no-inference pin"
        )

    return {
        "enabled": True,
        "provider": lock.identity["provider"],
        "custom_port": lock.p2p["custom_port"],
        "topology_receipt_cid": validation.receipt_cid,
        "topology_receipt": dict(validation.receipt),
    }


def _default_model_manager_probe(lock: LeanstralRuntimeLock) -> list[dict[str, Any]]:
    with _preserve_import_path():
        try:
            manager_module = import_source_bound_ipfs_accelerate(
                "ipfs_accelerate_py.model_manager"
            )
            ModelManager = getattr(manager_module, "ModelManager")
            if not callable(ModelManager):
                raise AttributeError("ModelManager is not callable")
        except (SourceBoundImportError, AttributeError) as exc:
            raise LeanstralProvisioningError(
                "model-manager discovery is unavailable"
            ) from exc
        with tempfile.TemporaryDirectory(
            prefix="hssl-leanstral-model-manager-"
        ) as state_dir:
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
    with _preserve_import_path():
        try:
            import anyio

            manager_module = import_source_bound_ipfs_accelerate(
                "ipfs_accelerate_py.model_manager"
            )
            tools_module = import_source_bound_ipfs_accelerate(
                "ipfs_accelerate_py.mcp_server.tools.model_tools.native_model_tools"
            )
            ModelManager = getattr(manager_module, "ModelManager")
            model_list_served = getattr(tools_module, "model_list_served")
            get_default_model_manager = getattr(
                manager_module,
                "get_default_model_manager",
            )
            if not all(
                callable(value)
                for value in (
                    ModelManager,
                    model_list_served,
                    get_default_model_manager,
                )
            ):
                raise AttributeError(
                    "MCP model discovery callables are unavailable"
                )
        except (ImportError, SourceBoundImportError, AttributeError) as exc:
            raise LeanstralProvisioningError(
                "MCP model discovery is unavailable"
            ) from exc

        async def call() -> dict[str, Any]:
            return await model_list_served(
                endpoint_url=lock.identity["endpoint"],
                timeout=float(lock.http["timeout_seconds"]),
            )

        with tempfile.TemporaryDirectory(
            prefix="hssl-leanstral-mcp-manager-"
        ) as state_dir:
            manager = ModelManager(
                storage_path=str(Path(state_dir) / "models.json"),
                use_database=False,
                enable_ipfs=False,
            )
            original_get_default = get_default_model_manager
            manager_module.get_default_model_manager = lambda: manager
            try:
                result = anyio.run(call)
            finally:
                manager_module.get_default_model_manager = original_get_default
                close = getattr(manager, "close", None)
                if callable(close):
                    close()
        if result.get("status") != "success" or not isinstance(
            result.get("models"), list
        ):
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
            and str(
                record.get("transport_model_id")
                or record.get("id")
                or record.get("model")
                or record.get("model_id")
                or ""
            )
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
        "topology_task_id": TOPOLOGY_TASK_ID,
        "lock_cid": lock.lock_cid,
        "lock_binding": _lock_binding_policy(),
        # Frozen HSSL-G112 compatibility; never authoritative for schema v2.
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
        "receipt_binding": _receipt_binding_policy(),
    }
    if receipt["health"]["server_build"] != lock.identity["server_build"]:
        raise LeanstralProvisioningError("health server build differs from the lock")
    unsigned_receipt = dict(receipt)
    receipt["receipt_cid"] = cid_for_dag_json(unsigned_receipt)
    # Frozen HSSL-G112 compatibility over the same unsigned receipt body.
    receipt["receipt_sha256"] = semantic_sha256(unsigned_receipt)
    return receipt


def validate_receipt(lock: LeanstralRuntimeLock, receipt: Mapping[str, Any]) -> None:
    """Revalidate a serialized health receipt and its content digest."""

    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise LeanstralProvisioningError("receipt schema mismatch")
    if receipt.get("topology_task_id") != TOPOLOGY_TASK_ID:
        raise LeanstralProvisioningError("receipt topology task identity mismatch")
    supplied_lock_cid = receipt.get("lock_cid")
    try:
        canonical_lock_cid = validate_cid(
            supplied_lock_cid,
            codecs=("dag-json",),
        )
    except (TypeError, ValueError) as exc:
        raise LeanstralProvisioningError(
            "receipt authoritative lock CID is missing or malformed"
        ) from exc
    if canonical_lock_cid != lock.lock_cid:
        raise LeanstralProvisioningError(
            "receipt authoritative lock CID is not bound to the canonical lock"
        )
    if receipt.get("lock_binding") != _lock_binding_policy():
        raise LeanstralProvisioningError(
            "receipt lock binding policy does not identify lock_cid as authoritative"
        )
    if receipt.get("lock_sha256") != lock.lock_sha256:
        raise LeanstralProvisioningError(
            "receipt legacy compatibility lock_sha256 mismatch"
        )
    if receipt.get("identity") != dict(lock.identity):
        raise LeanstralProvisioningError("receipt identity mismatch")
    if receipt.get("receipt_binding") != _receipt_binding_policy():
        raise LeanstralProvisioningError(
            "receipt binding policy does not identify receipt_cid as authoritative"
        )
    supplied_cid = receipt.get("receipt_cid")
    supplied_sha256 = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_cid", None)
    unsigned.pop("receipt_sha256", None)
    try:
        canonical_receipt_cid = validate_cid(
            supplied_cid,
            codecs=("dag-json",),
        )
    except (TypeError, ValueError) as exc:
        raise LeanstralProvisioningError(
            "receipt authoritative CID is missing or malformed"
        ) from exc
    if canonical_receipt_cid != cid_for_dag_json(unsigned):
        raise LeanstralProvisioningError("receipt authoritative CID mismatch")
    if (
        not isinstance(supplied_sha256, str)
        or not _SHA256_RE.fullmatch(supplied_sha256)
    ):
        raise LeanstralProvisioningError(
            "receipt legacy compatibility SHA-256 is missing or malformed"
        )
    if semantic_sha256(unsigned) != supplied_sha256:
        raise LeanstralProvisioningError(
            "receipt legacy compatibility SHA-256 mismatch"
        )
    serialized = json.dumps(receipt, sort_keys=True).lower()
    if any(f'"{key}"' in serialized for key in _SECRET_KEYS):
        raise LeanstralProvisioningError("receipt contains a secret-bearing field")
    if receipt.get("attach_only") is not True or receipt.get("duplicate_server_started") is not False:
        raise LeanstralProvisioningError("receipt does not prove attach-only provisioning")
    if receipt.get("uses_benchmark_inputs") is not False or receipt.get("secrets_serialized") is not False:
        raise LeanstralProvisioningError("receipt violates input/secret safety")
    p2p = receipt.get("p2p")
    topology_receipt = (
        p2p.get("topology_receipt")
        if isinstance(p2p, Mapping)
        else None
    )
    revalidated_p2p = verify_p2p_evidence(lock, topology_receipt)
    if (
        not isinstance(p2p, Mapping)
        or p2p.get("topology_receipt_cid")
        != revalidated_p2p["topology_receipt_cid"]
        or topology_receipt.get("receipt_cid")
        != revalidated_p2p["topology_receipt_cid"]
    ):
        raise LeanstralProvisioningError(
            "receipt P2P topology CID does not match its observation"
        )
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
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "lock_cid": lock.lock_cid,
                        "lock_sha256": lock.lock_sha256,
                        "lock_sha256_role": "legacy_compatibility",
                    },
                    sort_keys=True,
                )
            )
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
                        "lock_cid": lock.lock_cid,
                        "lock_sha256": lock.lock_sha256,
                        "lock_sha256_role": "legacy_compatibility",
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
