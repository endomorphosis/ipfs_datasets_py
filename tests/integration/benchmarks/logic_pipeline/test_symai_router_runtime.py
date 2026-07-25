"""Runtime evidence for the pinned SyMAI -> existing llm_router route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import urllib.request

import pytest

from benchmarks.logic_pipeline import adapters, contracts
from scripts.benchmarks import provision_hssl_symai_router as provision


def _structured_response() -> str:
    return json.dumps(
        {
            "candidate_ir": {
                "propositions": [
                    "Every runtime receipt has exactly one effective identity."
                ],
            },
            "normalized_predicates": ["RuntimeReceipt", "HasOneIdentity"],
            "quantifiers": ["forall"],
            "entities": ["runtime identity receipt"],
            "ambiguity_flags": [],
            "confidence": 1.0,
            "validation_errors": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class _SmokeEngine:
    def __init__(
        self,
        *,
        provider: str = "ipfs_accelerate_py",
        model: str = "Leanstral-119B",
    ) -> None:
        self.provider = provider
        self.model = model
        self.arguments: list[object] = []

    def forward(self, argument: object):
        self.arguments.append(argument)
        return (
            [_structured_response()],
            {
                "backend": "llm_router",
                "effective_provider_name": self.provider,
                "effective_model_name": self.model,
                "resolved_provider_name": "leanstral_local",
                "resolved_model_name": (
                    "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
                ),
                "service_endpoint": "http://127.0.0.1:8080/v1",
                "routing_backend": "existing_leanstral_service",
            },
        )


def _fake_distribution(lock: provision.SymaiRouterLock):
    metadata_text = "Metadata-Version: 2.1\nName: symbolicai\nVersion: 1.14.0\n"
    adjusted = replace(
        lock,
        metadata_sha256=hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
    )
    distribution = SimpleNamespace(
        version=adjusted.version,
        read_text=lambda name: metadata_text if name == "METADATA" else None,
    )
    return adjusted, distribution


def test_lock_is_complete_exact_and_ast_evidence_is_public() -> None:
    lock = provision.load_lock()

    assert lock.distribution == "symbolicai"
    assert lock.import_name == "symai"
    assert lock.version == "1.14.0"
    assert lock.requirement == "symbolicai==1.14.0"
    assert lock.router_module == "ipfs_datasets_py.llm_router"
    assert lock.engine.endswith(".IPFSSyMAINeurosymbolicEngine")
    assert lock.provider == "ipfs_accelerate_py"
    assert lock.model == "Leanstral-119B"
    assert lock.symai_config_model == "ipfs:Leanstral-119B"
    assert lock.max_calls == 1
    assert lock.max_retries == 0
    assert lock.timeout_seconds <= 60
    assert lock.raw["smoke"]["response_format"] == "json_schema"
    assert lock.raw["safety"] == {
        "allow_local_fallback": False,
        "allow_model_fallback": False,
        "allow_provider_fallback": False,
        "noninteractive": True,
        "recursive_routing": False,
        "reuse_existing_model_service": True,
        "starts_model_manager": False,
        "starts_model_server": False,
    }
    assert provision.HSSLEV1118B52() == (
        "pinned SymbolicAI through the existing llm_router with identical "
        "requested and effective provider/model identities, secret-safe "
        "receipts, disabled fallback, and one bounded non-corpus smoke call"
    )


def test_lock_rejects_unknown_fields_and_unsafe_policy(tmp_path: Path) -> None:
    payload = json.loads(provision.DEFAULT_LOCK_PATH.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    invalid = tmp_path / "unknown.lock"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(provision.ProvisioningError) as exc:
        provision.load_lock(invalid)
    assert exc.value.code == "invalid_lock_keys"

    del payload["unexpected"]
    payload["safety"]["allow_model_fallback"] = True
    invalid = tmp_path / "fallback.lock"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(provision.ProvisioningError) as exc:
        provision.load_lock(invalid)
    assert exc.value.code == "unsafe_routing_policy"


def test_install_plan_is_exact_noninteractive_and_shell_free() -> None:
    lock = provision.load_lock()
    command = provision.provisioning_command(
        lock, python_executable="/isolated/venv/bin/python"
    )

    assert command == (
        "/isolated/venv/bin/python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "symbolicai==1.14.0",
    )
    calls: list[object] = []

    def runner(command: object, **kwargs: object):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    provision.install_locked_package(
        lock,
        python_executable="/isolated/venv/bin/python",
        runner=runner,
    )
    assert calls[0][0] == command
    assert "shell" not in calls[0][1]


def test_environment_aligns_capability_and_router_identities() -> None:
    lock = provision.load_lock()
    environment = provision.pinned_environment(lock, {"UNRELATED": "retained"})

    assert environment["HSSL_SYMAI_PROVIDER"] == lock.provider
    assert environment["HSSL_LLM_ROUTER_PROVIDER"] == lock.provider
    assert environment["HSSL_SYMAI_MODEL"] == lock.model
    assert environment["HSSL_LLM_ROUTER_MODEL"] == lock.model
    assert environment["IPFS_DATASETS_PY_LLM_PROVIDER"] == lock.provider
    assert environment["IPFS_DATASETS_PY_LLM_MODEL"] == lock.model
    assert environment["NEUROSYMBOLIC_ENGINE_MODEL"] == f"ipfs:{lock.model}"
    assert environment["IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"] == "0"
    assert environment["IPFS_DATASETS_PY_DISABLE_CODEX_FOR_SYMAI"] == "1"
    assert environment["IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE"] == "0"
    assert environment["UNRELATED"] == "retained"


def test_configuration_is_noninteractive_pinned_and_secret_free(
    tmp_path: Path,
) -> None:
    lock = provision.load_lock()
    digest = provision.configure_symai(lock, tmp_path)
    config_path = tmp_path / ".symai" / "symai.config.json"
    raw = config_path.read_text(encoding="utf-8")
    config = json.loads(raw)

    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert config["NEUROSYMBOLIC_ENGINE_MODEL"] == "ipfs:Leanstral-119B"
    assert config["NEUROSYMBOLIC_ENGINE_API_KEY"] == "ipfs"
    assert config["SYMBOLIC_ENGINE"] == "ipfs"
    assert "OPENAI_API_KEY" not in raw
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert provision.configure_symai(lock, tmp_path) == digest


def test_configuration_refuses_to_overwrite_a_secret_bearing_prefix(
    tmp_path: Path,
) -> None:
    lock = provision.load_lock()
    config_path = tmp_path / ".symai" / "symai.config.json"
    config_path.parent.mkdir(parents=True)
    secret = "operator-secret-must-survive-refusal"
    config_path.write_text(
        json.dumps(
            {
                "NEUROSYMBOLIC_ENGINE_MODEL": lock.symai_config_model,
                "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
                "SYMBOLIC_ENGINE": "ipfs",
                "SEARCH_ENGINE_API_KEY": secret,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(provision.ProvisioningError) as exc:
        provision.configure_symai(lock, tmp_path)

    assert exc.value.code == "symai_configuration_contains_secret"
    assert secret in config_path.read_text(encoding="utf-8")


def test_symai_import_uses_isolated_prefix_and_restores_process_state(
    tmp_path: Path,
) -> None:
    lock = provision.load_lock()
    provision.configure_symai(lock, tmp_path)
    observed: dict[str, object] = {}
    original_prefix = sys.prefix

    def importer(name: str) -> object:
        observed["name"] = name
        observed["prefix"] = sys.prefix
        observed["config_exists"] = (
            Path(sys.prefix) / ".symai" / "symai.config.json"
        ).is_file()
        return SimpleNamespace(__version__=lock.version)

    provision.prepare_symai_import(lock, tmp_path, importer=importer)

    assert observed == {
        "name": "symai",
        "prefix": str(tmp_path.resolve()),
        "config_exists": True,
    }
    assert sys.prefix == original_prefix


def test_secret_safe_probe_receipt_and_exact_artifact_checks(
    tmp_path: Path,
) -> None:
    lock, distribution = _fake_distribution(provision.load_lock())
    router_source = tmp_path / lock.router_source
    router_source.parent.mkdir(parents=True)
    router_source.write_text("# existing router\n", encoding="utf-8")
    secret = "never-serialize-this-provider-token"
    environment = provision.pinned_environment(
        lock,
        {
            "HSSL_SYMAI_API_KEY": secret,
            "HF_TOKEN": "",
        },
    )
    receipt = provision.probe_runtime(
        lock,
        repository_root=tmp_path,
        environ=environment,
        distribution_getter=lambda _name: distribution,
        spec_finder=lambda _name: object(),
    )
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "ready"
    assert receipt["package"]["effective_version"] == "1.14.0"
    assert receipt["router"]["existing_router"] is True
    assert receipt["credentials"]["HSSL_SYMAI_API_KEY"]["present"] is True
    assert len(receipt["credentials"]["HSSL_SYMAI_API_KEY"]["sha256"]) == 64
    assert receipt["credentials"]["HF_TOKEN"] == {"present": False}
    assert secret not in serialized
    assert "raw_output" not in serialized


def test_probe_fails_closed_on_version_artifact_or_module_drift(
    tmp_path: Path,
) -> None:
    lock, distribution = _fake_distribution(provision.load_lock())
    receipt = provision.probe_runtime(
        lock,
        repository_root=tmp_path,
        distribution_getter=lambda _name: SimpleNamespace(
            version="1.15.0",
            read_text=distribution.read_text,
        ),
        spec_finder=lambda _name: None,
    )

    assert receipt["status"] == "unavailable"
    assert set(receipt["errors"]) == {
        "symbolicai_version_mismatch",
        "symai_import_unavailable",
        "existing_router_unavailable",
        "configured_identity_mismatch",
    }


def test_probe_rejects_misaligned_symai_and_router_configuration(
    tmp_path: Path,
) -> None:
    lock, distribution = _fake_distribution(provision.load_lock())
    router_source = tmp_path / lock.router_source
    router_source.parent.mkdir(parents=True)
    router_source.write_text("# existing router\n", encoding="utf-8")
    environment = provision.pinned_environment(lock, {})
    environment["HSSL_LLM_ROUTER_MODEL"] = "provider-default"

    receipt = provision.probe_runtime(
        lock,
        repository_root=tmp_path,
        environ=environment,
        distribution_getter=lambda _name: distribution,
        spec_finder=lambda _name: object(),
    )

    assert receipt["status"] == "unavailable"
    assert receipt["errors"] == ["configured_identity_mismatch"]


def test_bounded_structured_smoke_uses_existing_router_identity_once() -> None:
    lock = provision.load_lock()
    engine = _SmokeEngine()
    factory_calls: list[tuple[object, str]] = []

    def factory(config: object, namespace: str) -> _SmokeEngine:
        factory_calls.append((config, namespace))
        return engine

    smoke = provision.run_structured_smoke(
        lock,
        engine_factory=factory,
        trace_getter=lambda: {
            "effective_provider_name": lock.provider,
            "effective_model_name": lock.model,
        },
    )

    assert smoke["identity_verified"] is True
    assert smoke["requested_provider"] == smoke["effective_provider"] == lock.provider
    assert smoke["requested_model"] == smoke["effective_model"] == lock.model
    assert smoke["calls"] == 1
    assert smoke["retries"] == 0
    assert smoke["starts_model_server"] is False
    assert smoke["starts_model_manager"] is False
    assert smoke["allow_local_fallback"] is False
    assert smoke["input_kind"] == "authored-non-corpus"
    assert "raw_output" not in smoke
    assert len(factory_calls) == 1
    config = factory_calls[0][0]
    assert config.provider == lock.provider
    assert config.model == lock.model
    assert config.max_retries == 0
    assert config.cache_enabled is False
    assert config.expected_inner_provider == "leanstral_local"
    assert config.expected_inner_model == (
        "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
    )
    assert config.expected_inner_endpoint == "http://127.0.0.1:8080/v1"
    assert config.expected_inner_backend == "existing_leanstral_service"
    assert len(engine.arguments) == 1
    argument = engine.arguments[0]
    assert argument.prop.response_format == adapters.SYMAI_RESPONSE_FORMAT
    assert provision.SMOKE_TEXT in argument.prop.prepared_input


def test_actual_engine_adapter_uses_pinned_service_and_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock = provision.load_lock()
    exact_model = "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
    calls: list[urllib.request.Request] = []
    timeouts: list[float] = []

    class Response:
        def __init__(self, value: object) -> None:
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def urlopen(request: urllib.request.Request, *, timeout: float) -> Response:
        assert 0 < timeout <= lock.timeout_seconds
        timeouts.append(timeout)
        calls.append(request)
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": exact_model}]})
        if request.full_url.endswith("/chat/completions"):
            payload = json.loads(bytes(request.data or b"{}"))
            assert payload["model"] == exact_model
            assert payload["response_format"] == adapters.SYMAI_RESPONSE_FORMAT
            schema = payload["response_format"]["json_schema"]["schema"]
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == {
                "candidate_ir",
                "normalized_predicates",
                "quantifiers",
                "entities",
                "ambiguity_flags",
                "confidence",
                "validation_errors",
            }
            assert (
                schema["properties"]["candidate_ir"]["properties"][
                    "propositions"
                ]["maxItems"]
                == 12
            )
            assert payload["messages"][0] == {
                "role": "system",
                "content": (
                    "Return exactly one valid JSON object. Do not use Markdown "
                    "fences or emit any text before or after the object."
                ),
            }
            assert payload["seed"] == 0
            assert payload["stop"] == [
                "<|im_end|>",
                "<|tool_call_end|>",
                "<|im_start|>",
            ]
            return Response(
                {
                    "model": exact_model,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": _structured_response()},
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected URL: {request.full_url}")

    environment = provision.pinned_environment(lock)
    with provision.temporary_environment(environment):
        provision.configure_symai(lock, tmp_path)
        provision.prepare_symai_import(lock, tmp_path)
        router = importlib.import_module("ipfs_datasets_py.llm_router")
        assert (
            router._PINNED_SYMAI_RESPONSE_FORMAT
            == adapters.SYMAI_RESPONSE_FORMAT
        )
        router_deps = importlib.import_module("ipfs_datasets_py.router_deps")
        router_deps.set_default_router_deps(router_deps.RouterDeps())
        monkeypatch.setattr(router, "_pinned_symai_urlopen", urlopen)
        monotonic = iter((100.0, 101.0, 129.0))
        monkeypatch.setattr(router.time, "monotonic", lambda: next(monotonic))

        manager_module = importlib.import_module(
            "ipfs_datasets_py.ml.accelerate_integration.manager"
        )

        def forbidden_fallback(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("pinned SyMAI route must not enter generic fallback")

        monkeypatch.setattr(
            manager_module.AccelerateManager,
            "run_inference",
            forbidden_fallback,
        )
        smoke = provision.run_structured_smoke(lock)

    assert smoke["resolved_provider"] == "leanstral_local"
    assert smoke["resolved_model"] == exact_model
    assert smoke["routing_backend"] == "existing_leanstral_service"
    assert [request.full_url for request in calls] == [
        "http://127.0.0.1:8080/v1/models",
        "http://127.0.0.1:8080/v1/chat/completions",
    ]
    assert timeouts == pytest.approx([29.0, 1.0])


def test_private_binding_bypasses_text_cache_and_preserves_route_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    manager_module = importlib.import_module(
        "ipfs_datasets_py.ml.accelerate_integration.manager"
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")

    def forbidden_manager(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("private binding must not enter AccelerateManager")

    monkeypatch.setattr(
        manager_module.AccelerateManager,
        "run_inference",
        forbidden_manager,
    )
    provider = router._get_accelerate_provider(router.RouterDeps())
    assert provider is not None

    exact_model = router._PINNED_SYMAI_LEANSTRAL_MODEL
    http_calls: list[str] = []

    class Response:
        def __init__(self, value: object) -> None:
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def urlopen(request: urllib.request.Request, *, timeout: float) -> Response:
        assert timeout > 0
        http_calls.append(request.full_url)
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": exact_model}]})
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["cache_prompt"] is False
        return Response(
            {
                "model": exact_model,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": _structured_response()},
                    }
                ],
            }
        )

    monkeypatch.setattr(router, "_pinned_symai_urlopen", urlopen)

    class StaleTextCache:
        def __init__(self) -> None:
            self.gets = 0
            self.sets = 0

        def get(self, _key: str) -> str:
            self.gets += 1
            return "stale-text-without-route-receipt"

        def set(self, _key: str, _value: object) -> None:
            self.sets += 1

    remote = StaleTextCache()
    deps = router.RouterDeps(remote_cache=remote)
    receipts: list[dict[str, str]] = []
    for _ in range(2):
        output = router.generate_text(
            "return structured semantics",
            model_name=router._PINNED_SYMAI_LEANSTRAL_ALIAS,
            provider="ipfs_accelerate_py",
            provider_instance=provider,
            deps=deps,
            allow_local_fallback=False,
            disable_model_retry=True,
            _symai_route_binding=dict(router._PINNED_SYMAI_ROUTE_BINDING),
            response_format=router._PINNED_SYMAI_RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=64,
        )
        assert output == _structured_response()
        receipts.append(router.get_last_generation_trace())

    assert remote.gets == remote.sets == 0
    assert deps.router_cache == {}
    assert len(http_calls) == 4
    for receipt in receipts:
        assert {
            key: receipt[key]
            for key in router._PINNED_SYMAI_TRACE_KEYS
        } == router._PINNED_SYMAI_ROUTE_BINDING


def test_route_trace_is_thread_local_across_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    manager_module = importlib.import_module(
        "ipfs_datasets_py.ml.accelerate_integration.manager"
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "0")

    class Manager:
        def run_inference(
            self,
            model_name: str,
            payload: object,
            task_type: str | None = None,
        ) -> dict[str, object]:
            assert model_name == "generic-model-alias"
            assert task_type == "text-generation"
            return {
                "text": "generic-output",
                "backend": "generic-manager",
                "model": "generic-resolved-model",
            }

    monkeypatch.setattr(manager_module, "AccelerateManager", Manager)
    provider = router._get_accelerate_provider(router.RouterDeps())
    assert provider is not None

    exact_model = router._PINNED_SYMAI_LEANSTRAL_MODEL

    class Response:
        def __init__(self, value: object) -> None:
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def urlopen(request: urllib.request.Request, *, timeout: float) -> Response:
        assert timeout > 0
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": exact_model}]})
        return Response(
            {
                "model": exact_model,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": _structured_response()},
                    }
                ],
            }
        )

    monkeypatch.setattr(router, "_pinned_symai_urlopen", urlopen)
    barrier = threading.Barrier(2)

    def pinned_call() -> tuple[str, dict[str, str]]:
        output = router.generate_text(
            "pinned",
            model_name=router._PINNED_SYMAI_LEANSTRAL_ALIAS,
            provider="ipfs_accelerate_py",
            provider_instance=provider,
            allow_local_fallback=False,
            disable_model_retry=True,
            _symai_route_binding=dict(router._PINNED_SYMAI_ROUTE_BINDING),
            response_format=router._PINNED_SYMAI_RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=64,
        )
        barrier.wait(timeout=5)
        return output, router.get_last_generation_trace()

    def generic_call() -> tuple[str, dict[str, str]]:
        output = router.generate_text(
            "generic",
            model_name="generic-model-alias",
            provider="ipfs_accelerate_py",
            provider_instance=provider,
            allow_local_fallback=False,
            disable_model_retry=True,
        )
        barrier.wait(timeout=5)
        return output, router.get_last_generation_trace()

    with ThreadPoolExecutor(max_workers=2) as executor:
        pinned_future = executor.submit(pinned_call)
        generic_future = executor.submit(generic_call)
        pinned_output, pinned_trace = pinned_future.result(timeout=10)
        generic_output, generic_trace = generic_future.result(timeout=10)

    assert pinned_output == _structured_response()
    assert generic_output == "generic-output"
    assert {
        key: pinned_trace[key]
        for key in router._PINNED_SYMAI_TRACE_KEYS
    } == router._PINNED_SYMAI_ROUTE_BINDING
    assert generic_trace["routing_backend"] == "generic-manager"
    assert generic_trace["resolved_model_name"] == "generic-resolved-model"
    assert "service_endpoint" not in generic_trace
    assert "resolved_provider_name" not in generic_trace


def test_pinned_symai_http_opener_disables_ambient_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    request = urllib.request.Request("http://127.0.0.1:8080/v1/models")
    captured_handlers: list[object] = []

    class Response:
        closed = False

        @staticmethod
        def geturl() -> str:
            return request.full_url

        def close(self) -> None:
            self.closed = True

    response = Response()

    class Opener:
        @staticmethod
        def open(
            opened_request: urllib.request.Request,
            *,
            timeout: float,
        ) -> Response:
            assert opened_request is request
            assert timeout == 1.0
            return response

    def build_opener(*handlers: object) -> Opener:
        captured_handlers.extend(handlers)
        return Opener()

    monkeypatch.setattr(router.urllib.request, "build_opener", build_opener)

    assert router._pinned_symai_urlopen(request, timeout=1.0) is response
    proxy_handlers = [
        handler
        for handler in captured_handlers
        if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert response.closed is False


def test_pinned_symai_http_opener_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    request = urllib.request.Request("http://127.0.0.1:8080/v1/models")
    captured_handlers: list[object] = []

    class Response:
        @staticmethod
        def geturl() -> str:
            return request.full_url

        @staticmethod
        def close() -> None:
            return None

    class Opener:
        @staticmethod
        def open(
            _request: urllib.request.Request,
            *,
            timeout: float,
        ) -> Response:
            assert timeout == 1.0
            return Response()

    def build_opener(*handlers: object) -> Opener:
        captured_handlers.extend(handlers)
        return Opener()

    monkeypatch.setattr(router.urllib.request, "build_opener", build_opener)
    router._pinned_symai_urlopen(request, timeout=1.0)

    redirect_handlers = [
        handler
        for handler in captured_handlers
        if isinstance(handler, router._PinnedSymaiNoRedirect)
    ]
    assert len(redirect_handlers) == 1
    assert (
        redirect_handlers[0].redirect_request(
            request,
            None,
            302,
            "redirect",
            {},
            "http://different.invalid/v1/models",
        )
        is None
    )


def test_pinned_symai_bounded_response_rejects_changed_final_url_without_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    request = urllib.request.Request("http://127.0.0.1:8080/v1/models")
    secret = "DO_NOT_LEAK_REDIRECT_TARGET"

    class Response:
        closed = False

        @staticmethod
        def geturl() -> str:
            return f"http://different.invalid/{secret}"

        def close(self) -> None:
            self.closed = True

    response = Response()

    class Opener:
        @staticmethod
        def open(
            _request: urllib.request.Request,
            *,
            timeout: float,
        ) -> Response:
            assert timeout == 1.0
            return response

    monkeypatch.setattr(
        router.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )

    with pytest.raises(
        RuntimeError,
        match="pinned Leanstral service request failed: RuntimeError",
    ) as caught:
        router._bounded_json_response(
            request,
            timeout=1.0,
            max_bytes=4096,
        )

    assert response.closed is True
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"data":[],"data":[]}',
        b'{"data":[{"id":"one","id":"two"}]}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
    ],
)
def test_pinned_service_envelope_rejects_duplicates_and_nonfinite_numbers(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return raw if size < 0 else raw[:size]

    monkeypatch.setattr(
        router,
        "_pinned_symai_urlopen",
        lambda _request, *, timeout: Response(),
    )

    with pytest.raises(RuntimeError, match="returned invalid JSON"):
        router._bounded_json_response(
            urllib.request.Request("http://127.0.0.1/test"),
            timeout=1.0,
            max_bytes=4096,
        )


@pytest.mark.parametrize("finish_reason", [None, "tool_calls"])
def test_pinned_service_rejects_nonterminal_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    exact_model = router._PINNED_SYMAI_LEANSTRAL_MODEL

    class Response:
        def __init__(self, value: object) -> None:
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def urlopen(request: urllib.request.Request, *, timeout: float) -> Response:
        assert timeout > 0
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": exact_model}]})
        return Response(
            {
                "model": exact_model,
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"content": _structured_response()},
                    }
                ],
            }
        )

    monkeypatch.setattr(router, "_pinned_symai_urlopen", urlopen)
    with pytest.raises(RuntimeError, match="returned an invalid choice"):
        router._generate_pinned_symai_leanstral(
            "prompt",
            kwargs={
                "response_format": router._PINNED_SYMAI_RESPONSE_FORMAT,
                "temperature": 0.0,
                "max_tokens": 64,
                "timeout": 2.0,
            },
        )


def test_pinned_service_types_length_without_fallback_or_cache_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    manager_module = importlib.import_module(
        "ipfs_datasets_py.ml.accelerate_integration.manager"
    )
    exact_model = router._PINNED_SYMAI_LEANSTRAL_MODEL
    calls: list[str] = []

    class Response:
        def __init__(self, value: object) -> None:
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def urlopen(request: urllib.request.Request, *, timeout: float) -> Response:
        assert timeout > 0
        calls.append(request.full_url)
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": exact_model}]})
        return Response(
            {
                "model": exact_model,
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "{\"candidate_ir\":"},
                    }
                ],
            }
        )

    def forbidden_fallback(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("typed completion failure must not enter fallback")

    monkeypatch.setattr(router, "_pinned_symai_urlopen", urlopen)
    monkeypatch.setattr(
        manager_module.AccelerateManager,
        "run_inference",
        forbidden_fallback,
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    deps = router.RouterDeps()
    provider = router._get_accelerate_provider(deps)
    assert provider is not None

    with pytest.raises(router.PinnedSymaiCompletionError) as exc:
        router.generate_text(
            "return structured semantics",
            model_name=router._PINNED_SYMAI_LEANSTRAL_ALIAS,
            provider="ipfs_accelerate_py",
            provider_instance=provider,
            deps=deps,
            allow_local_fallback=False,
            disable_model_retry=True,
            _symai_route_binding=dict(router._PINNED_SYMAI_ROUTE_BINDING),
            response_format=router._PINNED_SYMAI_RESPONSE_FORMAT,
            temperature=0.0,
            max_tokens=512,
        )

    assert exc.value.safe_failure_class == "output_token_limit"
    assert str(exc.value) == (
        "pinned SyMAI completion failed: output_token_limit"
    )
    assert calls == [
        "http://127.0.0.1:8080/v1/models",
        "http://127.0.0.1:8080/v1/chat/completions",
    ]
    assert deps.router_cache == {}


def test_symai_engine_preserves_typed_completion_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock = provision.load_lock()
    provision.configure_symai(lock, tmp_path)
    provision.prepare_symai_import(lock, tmp_path)
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    engine_module = importlib.import_module(
        "ipfs_datasets_py.utils.symai_ipfs_engine"
    )
    error = router.PinnedSymaiCompletionError(
        router.PinnedSymaiCompletionError.OUTPUT_TOKEN_LIMIT
    )

    def raise_limit(*_args: object, **_kwargs: object) -> str:
        raise error

    monkeypatch.setattr(router, "generate_text", raise_limit)
    with pytest.raises(router.PinnedSymaiCompletionError) as exc:
        engine_module._generate_text(
            "return structured semantics",
            router._PINNED_SYMAI_LEANSTRAL_ALIAS,
            provider="ipfs_accelerate_py",
            allow_local_fallback=False,
            response_format=router._PINNED_SYMAI_RESPONSE_FORMAT,
            route_binding=router._PINNED_SYMAI_ROUTE_BINDING,
        )

    assert exc.value is error


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("symbolicai", "Leanstral-119B"),
        ("ipfs_accelerate_py", "fallback-model"),
        ("", "Leanstral-119B"),
    ],
)
def test_smoke_rejects_recursive_missing_or_drifted_effective_identity(
    provider: str,
    model: str,
) -> None:
    lock = provision.load_lock()
    engine = _SmokeEngine(provider=provider, model=model)

    with pytest.raises(provision.ProvisioningError) as exc:
        provision.run_structured_smoke(
            lock,
            engine_factory=lambda _config, _namespace: engine,
            trace_getter=lambda: {},
        )
    assert exc.value.code == "structured_smoke_failed"
    assert len(engine.arguments) == 1


def test_adapter_itself_fails_closed_on_identity_drift() -> None:
    lock = provision.load_lock()
    engine = _SmokeEngine(model="provider-default")
    adapter = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            provider=lock.provider,
            model=lock.model,
            max_retries=0,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {},
    )
    request = adapters.StageRequest(
        run_id="identity-drift",
        case_id="non-corpus",
        case_manifest_sha256="a" * 64,
        variant_id="A4",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"text": provision.SMOKE_TEXT},
        requested_identity={
            "provider": lock.provider,
            "model": lock.model,
        },
        environment_sha256="b" * 64,
    )

    record = adapter.run(request)

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
    )
    assert "identity mismatch" in (record.failure_detail or "")
    assert record.telemetry.retries == 0


def test_symai_engine_forbids_default_model_retry_on_pinned_route() -> None:
    source = (
        provision.REPOSITORY_ROOT
        / "ipfs_datasets_py"
        / "utils"
        / "symai_ipfs_engine.py"
    ).read_text(encoding="utf-8")

    assert "disable_model_retry=not allow_local_fallback" in source
    assert "allow_local_fallback=allow_local_fallback" in source


def test_receipt_is_canonical_create_only_and_cli_check_is_hermetic(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "runtime.json"
    receipt = {"z": 1, "a": {"safe": True}}
    provision.write_receipt(receipt_path, receipt)
    assert receipt_path.read_text(encoding="utf-8") == (
        '{"a":{"safe":true},"z":1}\n'
    )
    with pytest.raises(provision.ProvisioningError) as exc:
        provision.write_receipt(receipt_path, receipt)
    assert exc.value.code == "receipt_already_exists"

    completed = subprocess.run(
        [
            sys.executable,
            str(
                provision.REPOSITORY_ROOT
                / "scripts"
                / "benchmarks"
                / "provision_hssl_symai_router.py"
            ),
            "--check",
        ],
        cwd=provision.REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    cli_receipt = json.loads(completed.stdout)
    assert cli_receipt["status"] == "ready"
    assert cli_receipt["identity"]["requested_provider"] == "ipfs_accelerate_py"
    assert cli_receipt["identity"]["requested_model"] == "Leanstral-119B"
    assert cli_receipt["smoke"] is None
