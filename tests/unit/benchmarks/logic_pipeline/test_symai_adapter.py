"""Executable evidence for the strict existing-router SyMAI adapter."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import adapters, contracts


SHA_A = "a" * 64
SHA_B = "b" * 64
TEXT = "Every licensed agency must file an annual report."
INNER_PROVIDER = "leanstral_local"
INNER_MODEL = "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
INNER_ENDPOINT = "http://127.0.0.1:8080/v1"
INNER_BACKEND = "existing_leanstral_service"


def _request(
    *,
    run_id: str = "run-symai-001",
    variant_id: str = "A4",
    split: contracts.Split = contracts.Split.PILOT,
    cache_mode: contracts.CacheMode = contracts.CacheMode.COLD,
    input_data: object | None = None,
    requested_identity: Mapping[str, object] | None = None,
) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id=run_id,
        case_id="case-symai-001",
        case_manifest_sha256=SHA_A,
        variant_id=variant_id,
        split=split,
        cache_mode=cache_mode,
        input_data={"text": TEXT} if input_data is None else input_data,
        requested_identity=(
            {
                "implementation": "symai",
                "provider": "ipfs_accelerate_py",
                "model": "Leanstral-119B",
            }
            if requested_identity is None
            else requested_identity
        ),
        environment_sha256=SHA_B,
    )


def _telemetry(
    *,
    model_calls: int = 1,
    cache_hits: int = 0,
    cache_misses: int = 1,
    retries: int = 0,
) -> contracts.TelemetryRecord:
    return contracts.TelemetryRecord(
        wall_time_ms=2.0,
        cpu_time_ms=1.0,
        input_items=1,
        output_items=1,
        model_calls=model_calls,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        retries=retries,
        bytes_in=len(TEXT.encode("utf-8")),
        bytes_out=512,
        resource_lane=contracts.ResourceLane.MODEL,
    )


def _contract(
    *,
    confidence: object = 0.91,
    candidate_ir: object | None = None,
    validation_errors: object | None = None,
) -> str:
    return json.dumps(
        {
            "candidate_ir": (
                {
                    "kind": "fol",
                    "formula": "forall x. LicensedAgency(x) -> MustFileAnnualReport(x)",
                }
                if candidate_ir is None
                else candidate_ir
            ),
            "normalized_predicates": [
                "LicensedAgency",
                "MustFileAnnualReport",
            ],
            "quantifiers": ["forall"],
            "entities": ["agency", "annual report"],
            "ambiguity_flags": ["modal_scope"],
            "confidence": confidence,
            "validation_errors": (
                [] if validation_errors is None else validation_errors
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class _FakeEngine:
    def __init__(
        self,
        responses: list[object],
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.metadata = {
            "backend": "llm_router",
            "effective_provider_name": "ipfs_accelerate_py",
            "effective_model_name": "Leanstral-119B",
            "resolved_provider_name": INNER_PROVIDER,
            "resolved_model_name": INNER_MODEL,
            "service_endpoint": INNER_ENDPOINT,
            "routing_backend": INNER_BACKEND,
            **dict(metadata or {}),
        }
        self.calls: list[object] = []

    def forward(self, argument: object):
        self.calls.append(argument)
        if not self.responses:
            raise AssertionError("unexpected SyMAI engine call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return [response], dict(self.metadata)


def _configured(
    engine: _FakeEngine,
    *,
    config: adapters.SymaiAdapterConfig | None = None,
    cache: dict[str, object] | None = None,
) -> adapters.SymaiAdapter:
    return adapters.SymaiAdapter(
        config=config
        or adapters.SymaiAdapterConfig(
            model="Leanstral-119B",
            max_retries=1,
            expected_inner_provider=INNER_PROVIDER,
            expected_inner_model=INNER_MODEL,
            expected_inner_endpoint=INNER_ENDPOINT,
            expected_inner_backend=INNER_BACKEND,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {
            "effective_provider_name": "ipfs_accelerate_py",
            "effective_model_name": "Leanstral-119B",
            "resolved_provider_name": INNER_PROVIDER,
            "resolved_model_name": INNER_MODEL,
            "service_endpoint": INNER_ENDPOINT,
            "routing_backend": INNER_BACKEND,
        },
        cache={} if cache is None else cache,
    )


def test_objective_evidence_and_config_bounds_are_public() -> None:
    assert adapters.HSSLEV0328B3A() == (
        "strict SyMAI semantic contracts through the existing llm_router with "
        "bounded retries and isolated cache namespaces"
    )
    assert adapters.SYMAI_EVIDENCE_SCHEMA.endswith("symai-evidence.v1")
    assert adapters.SYMAI_ROUTER_ENGINE.endswith(
        "IPFSSyMAINeurosymbolicEngine"
    )
    assert adapters.SYMAI_MAX_RETRIES == 2
    assert adapters.SYMAI_RESPONSE_FORMAT["type"] == "json_schema"
    schema = adapters.SYMAI_RESPONSE_FORMAT["json_schema"]["schema"]
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

    with pytest.raises(contracts.ProtocolContractError):
        adapters.SymaiAdapterConfig(provider="symai")
    with pytest.raises(contracts.ProtocolContractError):
        adapters.SymaiAdapterConfig(model="../model")
    with pytest.raises(contracts.ProtocolContractError):
        adapters.SymaiAdapterConfig(max_retries=adapters.SYMAI_MAX_RETRIES + 1)
    with pytest.raises(contracts.ProtocolContractError):
        adapters.SymaiAdapterConfig(dry_run=1)  # type: ignore[arg-type]
    with pytest.raises(
        contracts.ProtocolContractError,
        match="must be supplied together",
    ):
        adapters.SymaiAdapterConfig(expected_inner_provider=INNER_PROVIDER)


def test_valid_semantics_cross_engine_and_preserve_raw_separately() -> None:
    raw = _contract()
    engine = _FakeEngine([raw])
    record = _configured(engine).run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.stage is contracts.StageName.SYMAI
    assert record.telemetry.resource_lane is contracts.ResourceLane.MODEL
    assert len(engine.calls) == 1
    argument = engine.calls[0]
    assert argument.prop.response_format == adapters.SYMAI_RESPONSE_FORMAT
    assert "Return exactly one JSON object" in argument.prop.prepared_input
    assert TEXT in argument.prop.prepared_input

    data = record.to_dict()["data"]
    assert data["schema"] == adapters.SYMAI_EVIDENCE_SCHEMA
    assert data["raw_output"] == raw
    assert data["candidate_ir"]["kind"] == "fol"
    assert data["candidate_ir_sha256"]
    assert data["normalized_predicates"] == [
        "LicensedAgency",
        "MustFileAnnualReport",
    ]
    assert data["quantifiers"] == ["forall"]
    assert data["entities"] == ["agency", "annual report"]
    assert data["ambiguity_flags"] == ["modal_scope"]
    assert data["confidence"] == 0.91
    assert data["validation_errors"] == []
    assert data["assurance"] == {
        "semantic_hypothesis": True,
        "raw_output_is_canonical": False,
        "contract_validated": True,
        "authoritative": False,
        "kernel_checked": False,
        "verified": False,
    }
    provenance = data["backend_provenance"]
    assert provenance["router"] == "ipfs_datasets_py.llm_router"
    assert provenance["engine"] == adapters.SYMAI_ROUTER_ENGINE
    assert provenance["starts_model_server"] is False
    assert provenance["reuses_existing_model_service"] is True
    assert not record.kernel_accepted
    assert record.kernel_receipt_sha256 is None


def test_prompt_is_concise_and_does_not_expose_the_cache_envelope() -> None:
    namespace = "run-secret/protocol/variant/split/cache"
    semantic_context = {
        "schema": adapters.SEMANTIC_CONTEXT_SCHEMA,
        "source_text_sha256": "1" * 64,
        "context_sha256": "2" * 64,
        "artifacts": [
            {
                "stage": "spacy",
                "status": "success",
                "evidence": {
                    "execution": {
                        "mode": "full_model",
                        "effective_model": "en_core_web_sm",
                        "pipeline": ["tok2vec", "tagger", "parser"],
                        "variant_id": "A4",
                        "configuration_sha256": "3" * 64,
                        "expected_class": "proved",
                    },
                    "normalized_predicates": ["LicensedAgency"],
                },
            }
        ],
    }

    prompt = adapters._symai_prompt(
        TEXT,
        namespace,
        semantic_context,
    )

    assert namespace not in prompt
    assert prompt.count(TEXT) == 1
    assert "OUTPUT_SKELETON" in prompt
    assert '"candidate_ir":{"propositions":[]}' in prompt
    assert "under 1600 UTF-8 bytes" in prompt
    assert "Never copy input-envelope or provenance keys" in prompt
    assert "do not add wrapper keys" in prompt
    assert '"mode":"full_model"' in prompt
    assert '"effective_model":"en_core_web_sm"' in prompt
    assert "variant_id" not in prompt
    assert "configuration_sha256" not in prompt
    assert "expected_class" not in prompt
    assert '"A4"' not in prompt
    assert "3" * 64 not in prompt
    assert len(prompt.encode("utf-8")) < 4 * 1024


def test_success_round_trip_and_digest_are_stable_for_fixed_measurement() -> None:
    raw = _contract()
    first = _configured(_FakeEngine([raw])).run(
        _request(), telemetry=_telemetry()
    )
    second = _configured(_FakeEngine([raw])).run(
        _request(), telemetry=_telemetry()
    )

    assert first.digest == second.digest
    restored = contracts.StageRecord.from_dict(first.to_dict())
    assert restored.digest == first.digest
    assert restored.to_dict() == first.to_dict()


def test_dry_run_is_deterministic_and_never_loads_or_calls_engine() -> None:
    factory_calls: list[object] = []

    def forbidden_factory(*args: object) -> object:
        factory_calls.append(args)
        raise AssertionError("dry-run must not load SyMAI or call a model")

    adapter = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            model="Leanstral-119B",
            dry_run=True,
        ),
        engine_factory=forbidden_factory,
    )
    first = adapter.run(
        _request(),
        telemetry=_telemetry(model_calls=0),
    )
    second = adapter.run(
        _request(),
        telemetry=_telemetry(model_calls=0),
    )

    assert not factory_calls
    assert first.status is contracts.StageStatus.SUCCESS
    assert first.digest == second.digest
    assert first.data["candidate_ir"]["kind"] == "dry_run"
    assert first.data["backend_provenance"]["dry_run"] is True
    assert first.data["backend_provenance"]["attempts"] == 0
    assert first.data["raw_output"]


def test_warm_cache_uses_complete_canonical_scope_and_avoids_second_call() -> None:
    engine = _FakeEngine([_contract()])
    shared_cache: dict[str, object] = {}
    adapter = _configured(engine, cache=shared_cache)
    request = _request(cache_mode=contracts.CacheMode.WARM)

    first = adapter.run(request)
    second = adapter.run(request)

    expected_namespace = contracts.CacheScope(
        request.run_id,
        request.protocol_sha256,
        request.variant_id,
        request.split,
        request.cache_mode,
    ).namespace
    assert len(engine.calls) == 1
    assert first.data["cache"]["namespace"] == expected_namespace
    assert first.data["cache"]["key"].startswith(
        f"{expected_namespace}/stage/symai/"
    )
    assert first.data["cache"]["hit"] is False
    assert second.data["cache"]["hit"] is True
    assert first.telemetry.cache_misses == 1
    assert second.telemetry.cache_hits == 1
    assert second.telemetry.model_calls == 0


def test_live_and_cached_results_require_complete_exact_inner_route_trace() -> None:
    missing_engine = _FakeEngine(
        [_contract()],
        metadata={"resolved_model_name": None},
    )
    missing = _configured(missing_engine).run(_request())

    assert missing.status is contracts.StageStatus.FAILED
    assert (
        missing.failure_code
        is contracts.FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
    )
    assert "omitted: resolved_model_name" in (missing.failure_detail or "")
    assert len(missing_engine.calls) == 1

    drift_engine = _FakeEngine(
        [_contract()],
        metadata={"service_endpoint": "http://127.0.0.1:9999/v1"},
    )
    drifted = _configured(drift_engine).run(_request())
    assert drifted.status is contracts.StageStatus.FAILED
    assert "identity drifted: service_endpoint" in (
        drifted.failure_detail or ""
    )

    shared_cache: dict[str, object] = {}
    cached_engine = _FakeEngine([_contract()])
    adapter = _configured(cached_engine, cache=shared_cache)
    request = _request(cache_mode=contracts.CacheMode.WARM)
    assert adapter.run(request).status is contracts.StageStatus.SUCCESS
    entry = next(iter(shared_cache.values()))
    assert isinstance(entry, dict)
    metadata = entry["metadata"]
    assert isinstance(metadata, dict)
    metadata.pop("routing_backend")

    cached = adapter.run(request)
    assert cached.status is contracts.StageStatus.FAILED
    assert "omitted: routing_backend" in (cached.failure_detail or "")
    assert cached.telemetry.cache_hits == 1
    assert cached.telemetry.model_calls == 0


def test_generic_config_without_inner_expectations_does_not_require_route_trace() -> None:
    engine = _FakeEngine(
        [_contract()],
        metadata={
            "resolved_provider_name": None,
            "resolved_model_name": None,
            "service_endpoint": None,
            "routing_backend": None,
        },
    )
    adapter = _configured(
        engine,
        config=adapters.SymaiAdapterConfig(
            model="Leanstral-119B",
            max_retries=0,
        ),
    )

    record = adapter.run(_request())

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["backend_provenance"]["router_metadata"] == {
        "backend": "llm_router",
        "effective_model_name": "Leanstral-119B",
        "effective_provider_name": "ipfs_accelerate_py",
    }


def test_cache_does_not_cross_run_variant_split_or_mode() -> None:
    engine = _FakeEngine([_contract() for _ in range(5)])
    shared_cache: dict[str, object] = {}
    adapter = _configured(engine, cache=shared_cache)
    requests = (
        _request(run_id="run-a", cache_mode=contracts.CacheMode.WARM),
        _request(run_id="run-b", cache_mode=contracts.CacheMode.WARM),
        _request(variant_id="A5", cache_mode=contracts.CacheMode.WARM),
        _request(
            split=contracts.Split.DEVELOPMENT,
            cache_mode=contracts.CacheMode.WARM,
        ),
        _request(cache_mode=contracts.CacheMode.COLD),
    )

    records = [adapter.run(request) for request in requests]

    assert len(engine.calls) == len(requests)
    assert len({record.data["cache"]["key"] for record in records}) == len(requests)
    assert not any(record.data["cache"]["hit"] for record in records)


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"candidate_ir": {}}',
        _contract(confidence=float("nan")),
        _contract(confidence=1.01),
        _contract(candidate_ir={"verified": True}),
        json.dumps(
            {
                **json.loads(_contract()),
                "unexpected": True,
            }
        ),
    ],
)
def test_malformed_json_or_contract_fails_closed_after_bound(raw: str) -> None:
    config = adapters.SymaiAdapterConfig(
        model="Leanstral-119B",
        max_retries=1,
    )
    engine = _FakeEngine([raw, raw])
    record = _configured(engine, config=config).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
    )
    assert record.output_sha256 is None
    assert not record.kernel_accepted
    assert record.data["candidate_ir"] is None
    assert len(engine.calls) == config.max_retries + 1
    assert record.telemetry.retries == config.max_retries


def test_malformed_contract_can_repair_once_with_bounded_retry() -> None:
    engine = _FakeEngine(["not-json", _contract()])
    record = _configured(engine).run(_request())

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(engine.calls) == 2
    assert record.telemetry.model_calls == 2
    assert record.telemetry.retries == 1
    assert record.data["backend_provenance"]["retries"] == 1
    assert (
        record.data["backend_provenance"]["repair_failure_class"]
        == "structured_contract_failure"
    )
    first_prompt = engine.calls[0].prop.prepared_input
    repair_prompt = engine.calls[1].prop.prepared_input
    assert first_prompt != repair_prompt
    assert "SAFE_REPAIR_CLASS:" not in first_prompt
    assert "SAFE_REPAIR_CLASS:structured_contract_failure" in repair_prompt
    assert "not-json" not in repair_prompt


def test_output_token_limit_is_typed_as_contract_failure_and_repairs_safely() -> None:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    limit_error = router.PinnedSymaiCompletionError(
        router.PinnedSymaiCompletionError.OUTPUT_TOKEN_LIMIT
    )
    engine = _FakeEngine([limit_error, limit_error])
    cache: dict[str, object] = {}
    record = _configured(engine, cache=cache).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
    )
    assert record.data["raw_output"] is None
    assert record.data["candidate_ir"] is None
    assert record.data["safe_failure_class"] == "output_token_limit"
    assert (
        record.provenance.effective_identity["symai_safe_failure_class"]
        == "output_token_limit"
    )
    assert "frozen output token limit" in (record.failure_detail or "")
    assert "RuntimeError" not in (record.failure_detail or "")
    assert record.telemetry.model_calls == 2
    assert record.telemetry.retries == 1
    assert cache == {}

    first_prompt = engine.calls[0].prop.prepared_input
    repair_prompt = engine.calls[1].prop.prepared_input
    assert first_prompt != repair_prompt
    assert "SAFE_REPAIR_CLASS:" not in first_prompt
    assert "SAFE_REPAIR_CLASS:output_token_limit" in repair_prompt
    assert "at most 4 short strings" in repair_prompt
    assert str(limit_error) not in repair_prompt


def test_oversized_raw_output_is_explicit_contract_failure() -> None:
    config = adapters.SymaiAdapterConfig(
        model="Leanstral-119B",
        max_retries=0,
        max_raw_output_bytes=128,
    )
    record = _configured(
        _FakeEngine([_contract()]),
        config=config,
    ).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
    )
    assert "exceeds 128" in (record.failure_detail or "")


@pytest.mark.parametrize("failure", [ImportError("missing"), SystemExit(1)])
def test_unavailable_package_or_import_configuration_is_explicit(
    failure: BaseException,
) -> None:
    def unavailable_factory(
        _config: adapters.SymaiAdapterConfig,
        _namespace: str,
    ) -> object:
        raise failure

    record = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(model="Leanstral-119B"),
        engine_factory=unavailable_factory,
    ).run(_request())

    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE
    assert "preflight configuration is unavailable" in (
        record.failure_detail or ""
    )
    assert (
        record.provenance.effective_identity["symai_failure_code"]
        == contracts.FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR.value
    )
    assert record.telemetry.model_calls == 0


def test_router_configuration_failure_retries_only_to_frozen_bound() -> None:
    engine = _FakeEngine([RuntimeError("router down")] * 3)
    config = adapters.SymaiAdapterConfig(
        model="Leanstral-119B",
        max_retries=2,
    )
    record = _configured(engine, config=config).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
    )
    assert len(engine.calls) == adapters.SYMAI_MAX_RETRIES + 1
    assert record.telemetry.retries == adapters.SYMAI_MAX_RETRIES
    prompts = [call.prop.prepared_input for call in engine.calls]
    assert "SAFE_REPAIR_CLASS:" not in prompts[0]
    assert all(
        "SAFE_REPAIR_CLASS:engine_invocation_failure" in prompt
        for prompt in prompts[1:]
    )
    assert prompts[1] == prompts[2]
    assert "router down" not in prompts[1]


def test_recursive_route_stack_is_rejected_before_engine_call() -> None:
    engine = _FakeEngine([_contract()])
    record = _configured(engine).run(
        _request(
            requested_identity={
                "implementation": "symai",
                "routing_stack": ["compiler", "symai"],
            }
        )
    )

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
    )
    assert "recursive SyMAI" in (record.failure_detail or "")
    assert not engine.calls


def test_effective_router_recursion_is_rejected_without_retry() -> None:
    engine = _FakeEngine(
        [_contract()],
        metadata={"effective_provider_name": "symbolicai"},
    )
    adapter = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            model="Leanstral-119B",
            max_retries=2,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {},
    )
    record = adapter.run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert "resolved recursively" in (record.failure_detail or "")
    assert len(engine.calls) == 1
    assert record.telemetry.retries == 0


def test_default_factory_uses_existing_engine_without_starting_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: dict[str, object] = {}

    class ExistingEngine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed["args"] = args
            constructed["kwargs"] = kwargs

    symai_module = SimpleNamespace(__version__="test")
    engine_module = SimpleNamespace(
        IPFSSyMAINeurosymbolicEngine=ExistingEngine
    )

    def fake_import(name: str) -> object:
        if name == "symai":
            return symai_module
        if name == "ipfs_datasets_py.utils.symai_ipfs_engine":
            return engine_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(adapters.importlib, "import_module", fake_import)
    config = adapters.SymaiAdapterConfig(model="Leanstral-119B")
    engine = adapters._default_symai_engine_factory(config, "isolated/scope")

    assert isinstance(engine, ExistingEngine)
    assert constructed["args"] == (
        "neurosymbolic",
        "NEUROSYMBOLIC_ENGINE_MODEL",
    )
    kwargs = constructed["kwargs"]
    assert kwargs["provider"] == "ipfs_accelerate_py"
    assert kwargs["model_name"] == "Leanstral-119B"
    assert kwargs["cache_namespace"] == "isolated/scope"
    assert kwargs["allow_local_fallback"] is False
    assert kwargs["route_binding"] is None
    assert "server" not in kwargs


def test_unconfigured_and_explicit_handler_modes_remain_compatible() -> None:
    assert adapters.SymaiAdapter().handler is None
    generic = adapters.SymaiAdapter(
        lambda _request: {"candidate": "legacy-injected-handler"}
    ).run(_request(), telemetry=_telemetry())
    assert generic.status is contracts.StageStatus.SUCCESS
    assert generic.data == {"candidate": "legacy-injected-handler"}

    with pytest.raises(contracts.ProtocolContractError):
        adapters.SymaiAdapter(
            lambda _request: {},
            config=adapters.SymaiAdapterConfig(),
        )
