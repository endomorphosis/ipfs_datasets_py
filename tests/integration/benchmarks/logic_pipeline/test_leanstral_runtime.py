"""Integration evidence for the pinned, supervisor-owned Leanstral runtime.

These tests never contact a real model, open benchmark inputs, or start a
server.  Network and discovery dependencies are injected so the provisioning
contract can be exercised deterministically.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import urllib.request

import pytest


REPOSITORY_ROOT = Path(__file__).parents[4]
LOCK_PATH = REPOSITORY_ROOT / "benchmarks/logic_pipeline/runtime_env/leanstral.lock"
PROVISIONER_PATH = REPOSITORY_ROOT / "scripts/benchmarks/provision_hssl_leanstral.py"
_SPEC = importlib.util.spec_from_file_location(
    "_hssl_provision_leanstral",
    PROVISIONER_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
provision = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = provision
_SPEC.loader.exec_module(provision)


def _lock_document() -> dict[str, object]:
    value = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_lock(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "leanstral.lock"
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _model_record(lock: provision.LeanstralRuntimeLock) -> dict[str, object]:
    return {
        "id": lock.identity["model"],
        "provider": lock.identity["provider"],
        "endpoint": lock.identity["endpoint"],
        "metadata": {
            "service_id": lock.identity["service"],
            "server_build": lock.identity["server_build"],
        },
    }


def _p2p_evidence(lock: provision.LeanstralRuntimeLock) -> dict[str, object]:
    peer_id = "12D3KooWLeanstralServicePeer"
    client_peer_id = "12D3KooWIndependentClientPeer"
    addresses = ["172.30.4.2", "10.8.0.99", "10.10.0.14"]
    advertised = [
        f"/ip4/{address}/tcp/19001/p2p/{peer_id}"
        for address in addresses
    ]
    return {
        "p2p_requested": True,
        "p2p_enabled": True,
        "listen_addrs": ["/ip4/0.0.0.0/tcp/19001"],
        "peer_id": peer_id,
        "advertised_multiaddrs": advertised,
        "interfaces": [
            {
                "interface": "wlP9s9",
                "address": "172.30.4.2",
                "is_up": True,
                "scope": "lan",
            },
            {
                "interface": "tun0",
                "address": "10.8.0.99",
                "is_up": True,
                "scope": "lan",
            },
            {
                "interface": "tun1",
                "address": "10.10.0.14",
                "is_up": True,
                "scope": "lan",
            },
            {
                "interface": "docker0",
                "address": "172.17.0.1",
                "is_up": False,
                "scope": "container",
            },
        ],
        "advertise_interface_allowlist": ["wlP9s9", "tun0", "tun1"],
        "bootstrap_exercises": [
            {
                "mechanism": "bootstrap",
                "target": lock.p2p["bootstrap_peers"][0],
                "attempted": True,
                "success": True,
                "timeout_s": 2.0,
                "duration_ms": 25.0,
                "error": None,
                "observer_peer_id": "",
                "namespace": "",
                "details": {},
            }
        ],
        "rendezvous_exercises": [
            {
                "mechanism": "rendezvous",
                "target": peer_id,
                "attempted": True,
                "success": True,
                "timeout_s": 2.0,
                "duration_ms": 30.0,
                "error": None,
                "observer_peer_id": client_peer_id,
                "namespace": lock.p2p["rendezvous"]["namespace"],
                "details": {},
            }
        ],
        "capabilities": {
            "mcp_stream": {
                "configured": True,
                "implemented": True,
                "advertised": True,
                "policy": "required",
            },
            "bootstrap": {
                "configured": True,
                "implemented": True,
                "advertised": True,
                "policy": "required",
            },
            "rendezvous": {
                "configured": True,
                "implemented": True,
                "advertised": True,
                "policy": "same_as_service_peer",
            },
            "pubsub": {
                "configured": False,
                "implemented": False,
                "advertised": False,
                "policy": "disabled_until_implemented",
            },
            "floodsub": {
                "configured": False,
                "implemented": False,
                "advertised": False,
                "policy": "disabled_until_implemented",
            },
        },
        "independent_dial": {
            "dialer_peer_id": client_peer_id,
            "target_peer_id": peer_id,
            "target_multiaddr": advertised[0],
            "attempted": True,
            "success": True,
            "timeout_s": 2.0,
            "duration_ms": 20.0,
            "error": None,
        },
        "served_models": [
            {
                "id": lock.identity["provider"],
                "model_id": lock.identity["provider"],
                "name": lock.identity["provider"],
                "logical_model_id": lock.identity["provider"],
                "transport_model_id": lock.identity["model"],
                "provider": "llamacpp",
                "transport": "llamacpp",
                "endpoint": lock.identity["endpoint"],
                "status": "available",
                "served": True,
                "capabilities": ["text-generation"],
                "metadata": {},
            }
        ],
        "server_instance_count": 1,
        "inference_attempted": False,
        "http_port": 8000,
        "notes": ["synthetic non-inference topology evidence"],
    }


class _JSONResponse:
    def __init__(
        self,
        value: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = json.dumps(value, sort_keys=True).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self) -> "_JSONResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class _RuntimeTransport:
    """Bounded HTTP double for health, models, and one non-corpus draft."""

    def __init__(self, lock: provision.LeanstralRuntimeLock) -> None:
        self.lock = lock
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> _JSONResponse:
        self.calls.append((request, timeout))
        if request.full_url == "http://127.0.0.1:8080/health":
            return _JSONResponse(
                {"status": "healthy", "server_build": self.lock.identity["server_build"]},
                headers={"Server": self.lock.identity["server_build"]},
            )
        if request.full_url == "http://127.0.0.1:8080/v1/models":
            return _JSONResponse(
                {"object": "list", "data": [_model_record(self.lock)]},
            )
        if request.full_url == "http://127.0.0.1:8080/v1/chat/completions":
            return _JSONResponse(
                {
                    "model": self.lock.identity["model"],
                    "choices": [{"message": {"content": "by exact rfl"}}],
                },
            )
        raise AssertionError(f"unexpected runtime URL: {request.full_url}")


def test_objective_symbol_and_lock_pin_one_exact_shared_identity() -> None:
    assert provision.HSSLEV1126C73() == (
        "shared Leanstral endpoint and model identity are health-verified and pinned"
    )
    assert provision.EVIDENCE_SYMBOL == "HSSLEV1126C73"

    document = _lock_document()
    lock = provision.load_lock(LOCK_PATH)

    assert document["schema_version"] == provision.LOCK_SCHEMA
    assert document["evidence"] == provision.EVIDENCE_SYMBOL
    assert document["task_id"] == "HSSL-BENCH-033"
    assert document["topology_task_id"] == "HSSL-G203"
    assert document["identity"] == {
        "endpoint": "http://127.0.0.1:8080/v1",
        "model": "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4",
        "provider": "leanstral_local",
        "server_build": "llama.cpp",
        "service": "leanstral-119b-shared",
    }
    assert lock.identity == document["identity"]
    with pytest.raises(FrozenInstanceError):
        lock.identity = {}  # type: ignore[misc]


@pytest.mark.parametrize(
    ("section", "key", "bad_value"),
    [
        ("identity", "endpoint", "http://127.0.0.1:8081/v1"),
        ("identity", "endpoint", "http://user:password@127.0.0.1:8080/v1?token=secret"),
        ("identity", "model", "some-fallback-model"),
        ("identity", "provider", "silently-substituted-provider"),
        ("identity", "service", "duplicate-model-server"),
        ("p2p", "required_provider", "silently-substituted-provider"),
        ("p2p", "custom_port", 0),
        ("p2p", "enabled", False),
        ("p2p", "probe_timeout_seconds", 60.0),
        ("p2p", "inference_allowed", True),
        ("http", "timeout_seconds", 0),
        ("http", "max_response_bytes", 0),
        ("smoke", "uses_benchmark_inputs", True),
    ],
)
def test_lock_rejects_identity_fallback_and_unbounded_or_corpus_configuration(
    tmp_path: Path,
    section: str,
    key: str,
    bad_value: object,
) -> None:
    document = _lock_document()
    nested = document[section]
    assert isinstance(nested, dict)
    nested[key] = bad_value

    with pytest.raises(provision.LeanstralProvisioningError):
        provision.load_lock(_write_lock(tmp_path, document))


def test_lock_digest_is_canonical_and_endpoint_sanitization_drops_secrets() -> None:
    from multiformats import CID

    document = _lock_document()
    lock = provision.load_lock(LOCK_PATH)

    decoded = CID.decode(lock.lock_cid)
    assert decoded.version == 1
    assert decoded.codec.name == "dag-json"
    assert decoded.hashfun.name == "sha2-256"
    assert lock.lock_cid == provision.cid_for_dag_json(document)
    # Frozen G112 compatibility only; v2 validation is authoritative on CID.
    assert lock.lock_sha256 == provision.semantic_sha256(document)
    assert len(lock.lock_sha256) == 64
    assert provision.sanitize_endpoint(
        "http://operator:password@127.0.0.1:8080/v1"
        "?api_key=secret&token=also-secret"
    ) == "http://127.0.0.1:8080/v1"


def test_proof_draft_stays_untrusted_until_independent_kernel_validation() -> None:
    lock = provision.load_lock(LOCK_PATH)
    draft = {
        "provider": lock.identity["provider"],
        "model": lock.identity["model"],
        "service": lock.identity["service"],
        "draft_text": "by exact rfl",
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
    }

    normalized = provision.verify_proof_draft(lock, draft)

    assert normalized["draft_text"] == "by exact rfl"
    assert normalized["assurance"] == "unverified"
    assert normalized["verified"] is False
    assert normalized["authoritative"] is False
    assert normalized["kernel_checked"] is False

    for claim in ("verified", "authoritative", "kernel_checked"):
        invalid = dict(draft)
        invalid[claim] = True
        with pytest.raises(provision.LeanstralProvisioningError, match=claim):
            provision.verify_proof_draft(lock, invalid)

    wrong_model = dict(draft, model="fallback-model")
    with pytest.raises(provision.LeanstralProvisioningError, match="model"):
        provision.verify_proof_draft(lock, wrong_model)


def test_attach_only_probe_binds_every_discovery_surface_and_safe_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from multiformats import CID

    lock = provision.load_lock(LOCK_PATH)
    transport = _RuntimeTransport(lock)
    manager_calls: list[provision.LeanstralRuntimeLock] = []
    mcp_calls: list[provision.LeanstralRuntimeLock] = []

    def manager_probe(received: provision.LeanstralRuntimeLock) -> list[dict[str, object]]:
        manager_calls.append(received)
        return [_model_record(received)]

    def mcp_probe(received: provision.LeanstralRuntimeLock) -> list[dict[str, object]]:
        mcp_calls.append(received)
        return [_model_record(received)]

    monkeypatch.setenv("HSSL_LEANSTRAL_API_KEY", "never-serialize-this-secret")
    receipt = provision.provision_shared_leanstral(
        lock,
        opener=transport,
        model_manager_probe=manager_probe,
        mcp_probe=mcp_probe,
        p2p_evidence=_p2p_evidence(lock),
    )

    provision.validate_receipt(lock, receipt)
    assert manager_calls == [lock]
    assert mcp_calls == [lock]
    assert receipt["identity"] == dict(lock.identity)
    assert receipt["health"] == {
        "status": "healthy",
        "server_build": lock.identity["server_build"],
    }
    assert receipt["http_model_list"] == dict(lock.identity)
    assert receipt["model_manager"] == dict(lock.identity)
    assert receipt["mcp"] == {
        "service": lock.mcp["service"],
        "list_tool": lock.mcp["list_tool"],
        "model": dict(lock.identity),
    }
    assert receipt["attach_only"] is True
    assert receipt["duplicate_server_started"] is False
    assert receipt["uses_benchmark_inputs"] is False
    assert receipt["secrets_serialized"] is False
    assert receipt["lock_cid"] == lock.lock_cid
    assert receipt["lock_binding"]["authoritative_field"] == "lock_cid"
    assert receipt["receipt_binding"]["authoritative_field"] == "receipt_cid"
    assert receipt["p2p"]["enabled"] is True
    assert receipt["p2p"]["provider"] == lock.identity["provider"]
    assert receipt["p2p"]["custom_port"] == provision.PINNED_P2P_PORT
    assert (
        receipt["p2p"]["topology_receipt"]["receipt_cid"]
        == receipt["p2p"]["topology_receipt_cid"]
    )
    assert (
        receipt["p2p"]["topology_receipt"]["observation"]["inference_attempted"]
        is False
    )
    assert receipt["proof_draft"]["draft_sha256"] == hashlib.sha256(
        b"by exact rfl"
    ).hexdigest()
    assert "draft_text" not in receipt["proof_draft"]
    assert receipt["proof_draft"]["verified"] is False
    assert receipt["proof_draft"]["authoritative"] is False
    assert receipt["proof_draft"]["kernel_checked"] is False
    assert receipt["proof_draft"]["kernel_receipt_sha256"] is None

    unsigned = dict(receipt)
    receipt_cid = unsigned.pop("receipt_cid")
    receipt_digest = unsigned.pop("receipt_sha256")
    decoded_receipt_cid = CID.decode(receipt_cid)
    assert decoded_receipt_cid.version == 1
    assert decoded_receipt_cid.codec.name == "dag-json"
    assert decoded_receipt_cid.hashfun.name == "sha2-256"
    assert receipt_cid == provision.cid_for_dag_json(unsigned)
    assert receipt_digest == provision.semantic_sha256(unsigned)
    serialized = json.dumps(receipt, sort_keys=True)
    assert "never-serialize-this-secret" not in serialized
    assert lock.smoke["prompt"] not in serialized

    assert [request.get_method() for request, _timeout in transport.calls] == [
        "GET",
        "GET",
        "POST",
    ]
    assert [timeout for _request, timeout in transport.calls] == [
        lock.http["timeout_seconds"],
        lock.http["timeout_seconds"],
        provision.PINNED_DRAFT_TIMEOUT_SECONDS,
    ]
    completion = transport.calls[-1][0]
    assert completion.get_header("Authorization") == "Bearer never-serialize-this-secret"
    payload = json.loads(completion.data.decode("utf-8"))
    assert payload == {
        "max_tokens": lock.smoke["max_tokens"],
        "messages": [{"content": lock.smoke["prompt"], "role": "user"}],
        "model": lock.identity["model"],
        "stream": False,
        "temperature": lock.smoke["temperature"],
    }


def test_real_llamacpp_and_model_manager_discovery_shapes_bind_logical_identity() -> None:
    lock = provision.load_lock(LOCK_PATH)

    class LlamaCppTransport(_RuntimeTransport):
        def __call__(
            self,
            request: urllib.request.Request,
            *,
            timeout: float,
        ) -> _JSONResponse:
            if request.full_url.endswith("/v1/models"):
                self.calls.append((request, timeout))
                return _JSONResponse(
                    {
                        "data": [
                            {
                                "id": lock.identity["model"],
                                "owned_by": "llamacpp",
                                "meta": {"n_ctx": 8192},
                            }
                        ]
                    }
                )
            return super().__call__(request, timeout=timeout)

    discovered = {
        "id": lock.identity["provider"],
        "model_id": lock.identity["provider"],
        "logical_model_id": lock.identity["provider"],
        "transport_model_id": lock.identity["model"],
        "provider": "llamacpp",
        "transport": "llamacpp",
        "endpoint": lock.identity["endpoint"],
        "status": "available",
        "served": True,
        "metadata": {"n_ctx": 8192},
    }
    receipt = provision.provision_shared_leanstral(
        lock,
        opener=LlamaCppTransport(lock),
        model_manager_probe=lambda _lock: [discovered],
        mcp_probe=lambda _lock: [discovered],
        p2p_evidence=_p2p_evidence(lock),
    )

    assert receipt["http_model_list"] == dict(lock.identity)
    assert receipt["model_manager"] == dict(lock.identity)
    assert receipt["mcp"]["model"] == dict(lock.identity)
    provision.validate_receipt(lock, receipt)


@pytest.mark.parametrize("surface", ["http", "model_manager", "mcp"])
def test_all_discovery_surfaces_fail_closed_on_identity_substitution(
    surface: str,
) -> None:
    lock = provision.load_lock(LOCK_PATH)
    transport = _RuntimeTransport(lock)
    wrong = _model_record(lock)
    wrong["provider"] = "silently-substituted-provider"

    if surface == "http":
        class WrongHTTP(_RuntimeTransport):
            def __call__(
                self,
                request: urllib.request.Request,
                *,
                timeout: float,
            ) -> _JSONResponse:
                if request.full_url.endswith("/v1/models"):
                    self.calls.append((request, timeout))
                    return _JSONResponse({"data": [wrong]})
                return super().__call__(request, timeout=timeout)

        transport = WrongHTTP(lock)
        manager_probe = lambda received: [_model_record(received)]
        mcp_probe = lambda received: [_model_record(received)]
    elif surface == "model_manager":
        manager_probe = lambda _received: [wrong]
        mcp_probe = lambda received: [_model_record(received)]
    else:
        manager_probe = lambda received: [_model_record(received)]
        mcp_probe = lambda _received: [wrong]

    with pytest.raises(
        provision.LeanstralProvisioningError,
        match="identity mismatch",
    ):
        provision.provision_shared_leanstral(
            lock,
            opener=transport,
            model_manager_probe=manager_probe,
            mcp_probe=mcp_probe,
            p2p_evidence=_p2p_evidence(lock),
            draft_probe=False,
        )


def test_probe_requires_exactly_one_model_and_enforces_response_bound() -> None:
    lock = provision.load_lock(LOCK_PATH)

    def duplicate_models(
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> _JSONResponse:
        del timeout
        if request.full_url.endswith("/health"):
            return _JSONResponse({"status": "ok", "server_build": "llama.cpp"})
        return _JSONResponse({"data": [_model_record(lock), _model_record(lock)]})

    with pytest.raises(provision.LeanstralProvisioningError, match="exactly one"):
        provision.provision_shared_leanstral(
            lock,
            opener=duplicate_models,
            model_manager_probe=lambda: [_model_record(lock)],
            mcp_probe=lambda: [_model_record(lock)],
            p2p_evidence=_p2p_evidence(lock),
            draft_probe=False,
        )

    class OversizeResponse(_JSONResponse):
        def __init__(self) -> None:
            super().__init__({"status": "ok"})
            self.headers = {
                "Content-Length": str(int(lock.http["max_response_bytes"]) + 1)
            }

    with pytest.raises(provision.LeanstralProvisioningError, match="byte bound"):
        provision.provision_shared_leanstral(
            lock,
            opener=lambda _request, timeout: OversizeResponse(),
            model_manager_probe=lambda: [_model_record(lock)],
            mcp_probe=lambda: [_model_record(lock)],
            p2p_evidence=_p2p_evidence(lock),
            draft_probe=False,
        )


def test_configured_p2p_requires_complete_cid_bound_non_inference_topology() -> None:
    from multiformats import CID

    lock = provision.load_lock(LOCK_PATH)
    valid = _p2p_evidence(lock)

    result = provision.verify_p2p_evidence(lock, valid)

    cid = CID.decode(result["topology_receipt_cid"])
    assert cid.version == 1
    assert cid.codec.name == "raw"
    assert cid.hashfun.name == "sha2-256"
    assert result["topology_receipt"]["validation"] == {
        "valid": True,
        "errors": [],
    }

    wrong_port = json.loads(json.dumps(valid))
    wrong_port["advertised_multiaddrs"][0] = (
        "/ip4/172.30.4.2/tcp/8000/p2p/12D3KooWLeanstralServicePeer"
    )
    failed_dial = json.loads(json.dumps(valid))
    failed_dial["independent_dial"]["success"] = False
    self_rendezvous = json.loads(json.dumps(valid))
    self_rendezvous["rendezvous_exercises"][0]["observer_peer_id"] = (
        self_rendezvous["peer_id"]
    )
    pubsub_overclaim = json.loads(json.dumps(valid))
    pubsub_overclaim["capabilities"]["pubsub"]["advertised"] = True
    inferred = json.loads(json.dumps(valid))
    inferred["inference_attempted"] = True

    for changed, message in (
        (wrong_port, "wrong_port"),
        (failed_dial, "independent_dial_not_successful"),
        (self_rendezvous, "not_independent"),
        (pubsub_overclaim, "pubsub"),
        (inferred, "inference_was_attempted"),
    ):
        with pytest.raises(provision.LeanstralProvisioningError, match=message):
            provision.verify_p2p_evidence(lock, changed)


def test_receipt_validation_detects_tampering_and_secret_fields() -> None:
    lock = provision.load_lock(LOCK_PATH)
    receipt = provision.provision_shared_leanstral(
        lock,
        opener=_RuntimeTransport(lock),
        model_manager_probe=lambda: [_model_record(lock)],
        mcp_probe=lambda: [_model_record(lock)],
        p2p_evidence=_p2p_evidence(lock),
        draft_probe=False,
    )

    tampered = dict(receipt, duplicate_server_started=True)
    with pytest.raises(
        provision.LeanstralProvisioningError,
        match="authoritative CID mismatch",
    ):
        provision.validate_receipt(lock, tampered)

    wrong_lock = dict(receipt, lock_cid=provision.cid_for_dag_json({"wrong": "lock"}))
    unsigned = dict(wrong_lock)
    unsigned.pop("receipt_cid")
    unsigned.pop("receipt_sha256")
    wrong_lock["receipt_cid"] = provision.cid_for_dag_json(unsigned)
    wrong_lock["receipt_sha256"] = provision.semantic_sha256(unsigned)
    with pytest.raises(
        provision.LeanstralProvisioningError,
        match="authoritative lock CID",
    ):
        provision.validate_receipt(lock, wrong_lock)

    secret_bearing = dict(receipt, api_key="do-not-write-secrets")
    unsigned = dict(secret_bearing)
    unsigned.pop("receipt_cid")
    unsigned.pop("receipt_sha256")
    secret_bearing["receipt_cid"] = provision.cid_for_dag_json(unsigned)
    secret_bearing["receipt_sha256"] = provision.semantic_sha256(unsigned)
    with pytest.raises(provision.LeanstralProvisioningError, match="secret"):
        provision.validate_receipt(lock, secret_bearing)

    missing_draft = dict(receipt, proof_draft=None)
    unsigned = dict(missing_draft)
    unsigned.pop("receipt_cid")
    unsigned.pop("receipt_sha256")
    missing_draft["receipt_cid"] = provision.cid_for_dag_json(unsigned)
    missing_draft["receipt_sha256"] = provision.semantic_sha256(unsigned)
    with pytest.raises(provision.LeanstralProvisioningError, match="untrusted"):
        provision.validate_receipt(lock, missing_draft)
