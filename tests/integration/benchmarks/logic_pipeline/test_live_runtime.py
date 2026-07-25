"""Integration evidence for capability-bound live runtime assembly."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from typing import Callable

import pytest

from benchmarks.logic_pipeline import adapters, capabilities, contracts, runtime


def _inventory(
    *,
    unavailable: frozenset[capabilities.CapabilityKind] = frozenset(),
) -> capabilities.CapabilityInventory:
    records = []
    for kind in capabilities.CapabilityKind:
        status = (
            capabilities.CapabilityStatus.UNAVAILABLE
            if kind in unavailable
            else capabilities.CapabilityStatus.AVAILABLE
        )
        identity: dict[str, object] = {"implementation": f"test-{kind.value}"}
        if kind is capabilities.CapabilityKind.SPACY_PIPELINE:
            identity["requested_model"] = "en_core_web_sm"
        if kind in {
            capabilities.CapabilityKind.SYMAI,
            capabilities.CapabilityKind.LLM_ROUTER,
        }:
            identity.update(
                requested_provider="test-provider",
                requested_model="test-model",
            )
        if kind is capabilities.CapabilityKind.LEANSTRAL_SERVICE:
            identity.update(
                endpoint="http://127.0.0.1:8080/v1",
                provider="leanstral_local",
                model="test-leanstral-model",
                routing_backend="existing_leanstral_service",
            )
        if kind is capabilities.CapabilityKind.LEAN_TOOLCHAIN:
            identity.update(
                lean={"path": "/test/lean", "version": "test"},
                lake={"path": "/test/lake", "version": "test"},
            )
        records.append(
            capabilities.CapabilityRecord(
                kind,
                status,
                identity,
                ("integration-test",),
                None if status is capabilities.CapabilityStatus.AVAILABLE else "absent",
            )
        )
    return capabilities.CapabilityInventory.create(
        "live-runtime-test",
        records,
        environment={"suite": "test"},
    )


def _handler(stage: contracts.StageName):
    def invoke(request: adapters.StageRequest) -> adapters.StageOutput:
        return adapters.StageOutput(
            data={"stage": stage.value},
            effective_identity={
                **dict(request.requested_identity),
                "backend": f"real-{stage.value}",
            },
        )

    return invoke


def _handlers(**overrides: object) -> runtime.RuntimeBackendHandlers:
    values = {
        "compiler": _handler(contracts.StageName.COMPILER),
        "spacy": _handler(contracts.StageName.SPACY),
        "symai": _handler(contracts.StageName.SYMAI),
        "legacy_symai": _handler(contracts.StageName.SYMAI),
        "hammer": _handler(contracts.StageName.HAMMER),
        "learned_hammer": _handler(contracts.StageName.HAMMER),
        "premise_ranked_hammer": _handler(contracts.StageName.HAMMER),
        "leanstral": _handler(contracts.StageName.LEANSTRAL),
        "kernel": _handler(contracts.StageName.KERNEL),
    }
    values.update(overrides)
    return runtime.RuntimeBackendHandlers(**values)


def test_ast_evidence_and_every_requested_live_stage_is_callable() -> None:
    live = runtime.build_live_runtime(_inventory(), _handlers())

    assert runtime.HSSLEV1142E95() == (
        "every frozen arm executes its real capability-bound bounded stage graph"
    )
    assert set(live.adapters) == {*(f"A{i}" for i in range(13)), "S1"}
    for variant, route in live.adapters.items():
        assert set(route) == set(
            __import__(
                "benchmarks.logic_pipeline.variants", fromlist=["x"]
            ).get_variant_definition(variant).stages
        )
        assert all(adapter.handler is not None for adapter in route.values())


def test_available_backend_cannot_remain_inert_and_unavailable_is_not_substituted() -> None:
    missing_hammer = _handlers(hammer=None)
    with pytest.raises(runtime.RuntimeBindingError, match="no live hammer handler"):
        runtime.build_live_runtime(
            _inventory(), missing_hammer, variant_ids=("A2",)
        )

    unavailable = runtime.build_live_runtime(
        _inventory(
            unavailable=frozenset({capabilities.CapabilityKind.HAMMER})
        ),
        missing_hammer,
        variant_ids=("A2",),
    )
    adapter = unavailable.adapters["A2"][contracts.StageName.HAMMER]
    assert adapter.handler is None
    request = adapters.StageRequest(
        run_id="live-runtime-test",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data={"text": "A policy applies."},
    )
    record = adapter.run(request)
    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE

    dishonest = runtime.build_live_runtime(
        _inventory(),
        _handlers(
            kernel=lambda _request: adapters.StageOutput(
                data={"accepted": True},
                kernel_accepted=True,
                kernel_receipt_sha256="d" * 64,
            )
        ),
        variant_ids=("A1",),
    )
    dishonest_record = dishonest.adapters["A1"][
        contracts.StageName.KERNEL
    ].run(
        adapters.StageRequest(
            run_id="live-runtime-test",
            case_id="case-1",
            case_manifest_sha256="a" * 64,
            variant_id="A1",
            input_data={"text": "A policy applies."},
        )
    )
    assert dishonest_record.status is contracts.StageStatus.FAILED
    assert not dishonest_record.kernel_accepted
    assert (
        dishonest_record.failure_code
        is contracts.FailureCode.SAFETY_CONTROL_FAILURE
    )


def test_default_leanstral_provider_is_bound_to_frozen_identity() -> None:
    inventory = _inventory()
    config = runtime._leanstral_provider_config(
        inventory.by_kind[capabilities.CapabilityKind.LEANSTRAL_SERVICE]
    )

    assert config.llm_provider == "leanstral_local"
    assert config.model == "test-leanstral-model"
    assert config.timeout_seconds == runtime.LEANSTRAL_MEASURED_TIMEOUT_SECONDS
    assert config.max_new_tokens == runtime.LEANSTRAL_MEASURED_MAX_NEW_TOKENS


def test_live_runtime_propagates_explicit_measured_leanstral_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    class Provider:
        def prove(self, _request: object) -> object:
            raise AssertionError("runtime assembly must not invoke the provider")

    def create_provider(config: object, **_identity: object) -> Provider:
        captured.append(config)
        return Provider()

    monkeypatch.setattr(
        runtime,
        "create_pinned_leanstral_provider",
        create_provider,
    )
    live = runtime.build_live_runtime(
        _inventory(),
        _handlers(leanstral=None),
        variant_ids=("A3",),
        leanstral_timeout_seconds=17.0,
        leanstral_max_new_tokens=321,
    )
    adapter = live.adapters["A3"][contracts.StageName.LEANSTRAL]

    assert len(captured) == 1
    assert captured[0].timeout_seconds == 17.0
    assert captured[0].max_new_tokens == 321
    assert adapter.config.model_timeout_seconds == 17.0
    assert adapter.config.model_token_limit == 321


def test_default_symai_route_binds_exact_leanstral_capability_identity() -> None:
    live = runtime.build_live_runtime(
        _inventory(),
        _handlers(symai=None),
        variant_ids=("A4",),
    )
    adapter = live.adapters["A4"][contracts.StageName.SYMAI]

    assert isinstance(adapter, adapters.SymaiAdapter)
    assert adapter.config is not None
    assert adapter.config.expected_inner_provider == "leanstral_local"
    assert adapter.config.expected_inner_model == "test-leanstral-model"
    assert (
        adapter.config.expected_inner_endpoint
        == "http://127.0.0.1:8080/v1"
    )
    assert (
        adapter.config.expected_inner_backend
        == "existing_leanstral_service"
    )


def test_current_compiler_projects_oversized_derived_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real codec boundary must fit a durable stage artifact."""

    full_modal_ir = {
        "document_id": "case-1",
        "normalized_text": "A policy applies.",
        "formulas": [{"operator": "must", "predicate": "applies"}],
        "source": "logic_pipeline_benchmark",
        "version": "1",
        # Production graph/ontology exports can be much larger than the
        # benchmark's 64 KiB artifact boundary.
        "metadata": {"ontology_export": "x" * (160 * 1024)},
    }
    monkeypatch.setattr(
        runtime,
        "_encode_current_modal",
        lambda _text, _document_id: (full_modal_ir, "spacy"),
    )
    request = adapters.StageRequest(
        run_id="live-runtime-test",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A0",
        input_data={"text": "A policy applies."},
    )

    record = adapters.CompilerAdapter(
        runtime._current_compiler_handler
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    durable_data = record.to_dict()["data"]
    assert durable_data["modal_ir"] == {
        key: full_modal_ir[key]
        for key in (
            "document_id",
            "formulas",
            "normalized_text",
            "source",
            "version",
        )
    }
    assert durable_data["modal_ir_sha256"] == hashlib.sha256(
        contracts.canonical_json(full_modal_ir).encode("utf-8")
    ).hexdigest()
    assert durable_data["modal_ir_canonical_bytes"] > 64 * 1024
    assert len(contracts.canonical_json(durable_data).encode("utf-8")) < 64 * 1024


def test_reviewed_obligation_compilation_is_deterministic_and_target_bound() -> None:
    value = {
        "obligation_id": "pilot-p01-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "trained",
        },
    }
    first = runtime.compile_reviewed_obligation(value)
    second = runtime.compile_reviewed_obligation(value)

    assert first is not None and second is not None
    assert first == second
    assert first.digest == second.digest
    assert first.semantic_target == "trained"
    assert first.obligation_sha256 == hashlib.sha256(
        contracts.canonical_json(value["proof_obligation"]).encode()
    ).hexdigest()
    assert first.obligation_sha256[:16] in first.source_template
    assert "{{PROOF}}" in first.source_template
    assert runtime.CompiledObligation.from_dict(first.to_dict()) == first

    mutated = runtime.compile_reviewed_obligation(
        {
            **value,
            "proof_obligation": {
                **value["proof_obligation"],
                "target": "changed",
            },
        }
    )
    assert mutated is not None and mutated.digest != first.digest
    injected = runtime.compile_reviewed_obligation(
        {
            **value,
            "proof_obligation": {
                **value["proof_obligation"],
                "target": "trained -/ theorem injected : False := by",
            },
        }
    )
    assert injected is not None
    assert injected.semantic_target.endswith("False := by")
    assert "theorem injected" not in injected.source_template
    with pytest.raises(runtime.RuntimeBindingError, match="unsupported"):
        runtime.compile_reviewed_obligation(
            {
                **value,
                "proof_obligation": {
                    "kind": "theorem",
                    "logic": "invented",
                    "target": "trained",
                },
            }
        )


def _reviewed_entailment(
    text: str,
    target: str,
    *,
    obligation_id: str = "reviewed-obligation",
) -> dict[str, object]:
    return {
        "text": text,
        "obligation_id": obligation_id,
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": target,
        },
    }


def test_reviewed_entailment_translation_is_source_bound_and_label_blind() -> None:
    value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
    )
    first = runtime.compile_reviewed_obligation(
        {**value, "expected_class": "proved", "expected_ir": {"target": "trained"}}
    )
    relabeled = runtime.compile_reviewed_obligation(
        {
            **value,
            "expected_class": "unsupported",
            "expected_ir": {"target": "unrelated"},
        }
    )

    assert first is not None and relabeled is not None
    assert first == relabeled
    translation = runtime._entailment_translation(
        value,
        theorem_name=first.theorem_name,
        obligation_sha256=first.obligation_sha256,
        kind=first.kind,
        logic=first.logic,
        semantic_target=first.semantic_target,
    )
    assert translation is not None
    assert translation.shape == "direct_unary_entailment"
    assert translation.native_proof_text == "exact rule witness fact"
    assert "(assert (not target))" in translation.smt2_problem
    assert "expected_class" not in first.source_template
    assert "expected_ir" not in first.source_template

    mismatched = runtime.compile_reviewed_obligation(
        {
            **value,
            "text": (
                "Every archivist is trained. Ada is an archivist. "
                "Therefore Ada is careful."
            ),
        }
    )
    assert mismatched is not None
    assert "translation:unsupported" in mismatched.source_template


def test_compiled_obligation_multiline_tactic_body_compiles_with_native_lean() -> None:
    lean = shutil.which("lean")
    if lean is None:
        pytest.skip("installed Lean executable is required for layout regression")
    value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
    )
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    proof = (
        "have hpremise := fact\n"
        "exact rule witness hpremise"
    )

    source = compiled.render(proof)

    assert "by\n  have hpremise := fact\n  exact rule witness hpremise" in source
    checked = subprocess.run(
        (lean, "-j", "1", "--stdin"),
        input=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_two_step_entailment_is_available_to_the_deterministic_a1_core() -> None:
    value = _reviewed_entailment(
        (
            "Every red item is warm. Every warm item is safe. "
            "Object R is red. Therefore object R is safe."
        ),
        "safe",
    )
    compiled = runtime.compile_reviewed_obligation(value)

    assert compiled is not None
    translation = runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is not None
    assert translation.shape == "two_step_unary_chain"
    assert translation.native_proof_text == (
        "exact second_rule witness (first_rule witness fact)"
    )
    assert translation.hammer_proof_text == (
        "exact second_rule witness (first_rule witness fact)"
    )


def _strict_compiler_artifact(
    value: dict[str, object],
) -> tuple[
    runtime.CompiledObligation,
    runtime.ReviewedEntailmentTranslation | None,
    adapters.StageArtifact,
]:
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    translation = runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    native_candidate = (
        None
        if translation is None or translation.native_proof_text is None
        else {
            "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
            "translation_sha256": translation.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "source_sha256": translation.source_sha256,
            "derivation": translation.shape,
            "certificate": translation.native_proof_text,
            "authoritative": False,
            "requires_independent_kernel": True,
        }
    )
    artifact = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": (
                None if translation is None else translation.to_dict()
            ),
            "entailment_translation_sha256": (
                None if translation is None else translation.digest
            ),
            "native_proof_candidate": native_candidate,
        },
        None,
        {"backend": "compiler"},
        0,
    )
    return compiled, translation, artifact


def _strict_leanstral_artifact(
    request: adapters.StageRequest,
    compiled: runtime.CompiledObligation,
    *,
    proof_text: str = "exact proof_token",
    boundary_overrides: dict[str, object] | None = None,
    draft_overrides: dict[str, object] | None = None,
) -> adapters.StageArtifact:
    expected = adapters._compiled_leanstral_context(
        request,
        adapters.LeanstralAdapterConfig(),
        compiled.obligation_id,
    )
    assert expected is not None
    context_capsule, theorem = expected
    provider = "leanstral_local"
    model = "exact-test-model"
    endpoint = "http://127.0.0.1:8080/v1"
    prompt = contracts.canonical_json(context_capsule)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    proof_sha256 = hashlib.sha256(proof_text.encode("utf-8")).hexdigest()
    normalized = json.dumps(
        {
            "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "theorem_id": compiled.theorem_name,
            "proposal_kind": "proof",
            "proof_text": proof_text,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    boundary = {
        "schema": adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
        "endpoint": endpoint,
        "provider": provider,
        "requested_model": model,
        "response_model": model,
        "prompt_sha256": prompt_sha256,
        "raw_model_content_sha256": hashlib.sha256(b"raw-model-output").hexdigest(),
        "raw_model_content_bytes": len(b"raw-model-output"),
        "normalized_proposal_sha256": hashlib.sha256(normalized).hexdigest(),
        "normalized_proposal_bytes": len(normalized),
        "normalization": "none",
    }
    if boundary_overrides:
        boundary.update(boundary_overrides)
    identity = {
        "schema_version": adapters.LEANSTRAL_DRAFT_SCHEMA,
        "llm_provider": provider,
        "model": model,
        "obligation_ids": [compiled.obligation_id],
        "canonical_source_digest": f"sha256:{compiled.source_template_sha256}",
        "theorem_id": compiled.theorem_name,
        "theorem_equivalence_key": theorem["equivalence_key"],
        "context_capsule_id": context_capsule["capsule_id"],
        "proposal_kind": "proof",
        "prompt_sha256": prompt_sha256,
        "output_sha256": proof_sha256,
    }
    artifact_id = "leanstral-draft-" + hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    repair_attempt = 0
    request_id = "leanstral-" + hashlib.sha256(
        (
            f"{request.run_id}:{request.case_id}:"
            f"{request.input_sha256}:{repair_attempt}"
        ).encode("utf-8")
    ).hexdigest()[:48]
    draft = {
        "schema_version": adapters.LEANSTRAL_DRAFT_SCHEMA,
        "artifact_id": artifact_id,
        "artifact_kind": "llm_output",
        "stage": "model_draft",
        "draft_text": proof_text,
        "proof_text": proof_text,
        "request_id": request_id,
        "llm_provider": provider,
        "model": model,
        "obligation_ids": [compiled.obligation_id],
        "canonical_source_digest": f"sha256:{compiled.source_template_sha256}",
        "prompt_sha256": prompt_sha256,
        "output_sha256": proof_sha256,
        "timeout_ms": int(
            adapters.LEANSTRAL_MEASURED_TIMEOUT_SECONDS * 1000
        ),
        "token_budget": adapters.LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
        "resource_class": "model",
        "theorem_id": compiled.theorem_name,
        "theorem_equivalence_key": theorem["equivalence_key"],
        "context_capsule_id": context_capsule["capsule_id"],
        "proposal_kind": "proof",
        "proposal_schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "decomposition": [],
        "reused_artifact_ids": [],
        "prompt_tokens": 1,
        "response_tokens": 1,
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "proof_attempted": False,
        "proof_success": False,
        "kernel_checked": False,
        "can_mutate_canonical_source": False,
        "can_mutate_obligations": False,
        "metadata": {
            "structured_output": True,
            "fixed_theorem_identity_digest": theorem["identity_digest"],
            "benchmark_generation_boundary": boundary,
        },
        "repair_attempt": repair_attempt,
        "benchmark_request_id": f"{request.run_id}:{request.case_id}",
    }
    if draft_overrides:
        draft.update(draft_overrides)
    evidence_without_id = {
        "schema": adapters.LEANSTRAL_EVIDENCE_SCHEMA,
        "obligation_id": compiled.obligation_id,
        "mode": "synthesis",
        "repair_attempts": repair_attempt,
        "max_repair_attempts": 1,
        "draft": draft,
        "trust": {
            "assurance": "unverified",
            "verified": False,
            "authoritative": False,
            "kernel_checked": False,
        },
        "resource_classes": {
            "model_inference": "model",
            "kernel_check": "kernel",
        },
    }
    evidence = {
        "evidence_id": hashlib.sha256(
            contracts.canonical_json(evidence_without_id).encode("utf-8")
        ).hexdigest(),
        **evidence_without_id,
    }
    return adapters.StageArtifact(
        contracts.StageName.LEANSTRAL,
        contracts.StageStatus.SUCCESS,
        evidence,
        None,
        {
            "backend": "leanstral",
            "provider": provider,
            "model": model,
        },
        1,
    )


def _strict_hammer_artifact(
    request: adapters.StageRequest,
    translation: runtime.ReviewedEntailmentTranslation,
    *,
    overrides: dict[str, object] | None = None,
) -> adapters.StageArtifact:
    solver_path = "/test/cvc5"
    proof_text = translation.hammer_proof_text
    data = {
        "schema": runtime.HAMMER_TRANSLATED_ENTAILMENT_SCHEMA,
        "case_input_sha256": request.input_sha256,
        "translation_status": "success",
        "translation_sha256": translation.digest,
        "translation_shape": translation.shape,
        "source_sha256": translation.source_sha256,
        "obligation_sha256": translation.obligation_sha256,
        "solver_status": "unsat",
        "solver_command_sha256": hashlib.sha256(
            f"{solver_path}\0--lang=smt2".encode("utf-8")
        ).hexdigest(),
        "solver_input_sha256": hashlib.sha256(
            translation.smt2_problem.encode("utf-8")
        ).hexdigest(),
        "stdout_sha256": hashlib.sha256(b"unsat\n").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "timed_out": False,
        "process_group_reaped": True,
        "proof_success": True,
        "proof_text": proof_text,
        "candidate_created": True,
        "native_reconstruction": {
            "strategy": translation.shape,
            "certificate_sha256": hashlib.sha256(
                proof_text.encode("utf-8")
            ).hexdigest(),
            "authoritative": False,
            "requires_independent_kernel": True,
        },
        "efficacy_observed": False,
    }
    if overrides:
        data.update(overrides)
    return adapters.StageArtifact(
        contracts.StageName.HAMMER,
        contracts.StageStatus.SUCCESS,
        data,
        None,
        {
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": solver_path,
            "translation": "reviewed-entailment-v1",
        },
        1,
    )


class _FakeSupervisor:
    def __init__(
        self,
        root: Path,
        *,
        returncode: int = 0,
        expected_proof: str = "exact proof_token",
    ) -> None:
        self.root = root
        self.returncode = returncode
        self.expected_proof = expected_proof
        self.active_process_count = 0
        self.closed = False

    @contextmanager
    def temporary_directory(self, **_kwargs: object):
        directory = self.root / "kernel"
        directory.mkdir()
        yield str(directory)

    def run(self, command: object, **_kwargs: object) -> object:
        source = Path(self.root / "kernel" / "Main.lean").read_text()
        assert f"by\n  {self.expected_proof}" in source
        assert tuple(command)[1:3] == ("-j", "1")
        assert _kwargs["limits"].memory_mb == 4096
        return SimpleNamespace(
            returncode=self.returncode,
            stdout="accepted" if self.returncode == 0 else "",
            stderr="" if self.returncode == 0 else "rejected",
            timed_out=False,
            cancelled=False,
            resource_exhausted=False,
            error=None,
            termination_reason="completed",
            wall_time_seconds=0.01,
        )

    def close(self) -> None:
        self.closed = True


def test_independent_kernel_receipt_binds_candidate_and_reaps_owner(
    tmp_path: Path,
) -> None:
    value = {
        "text": "target",
        "obligation_id": "obl-1",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "target",
        },
    }
    compiled, _, compiler = _strict_compiler_artifact(value)
    base_request = adapters.StageRequest(
        run_id="runtime-kernel",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A9",
        input_data=value,
        requested_identity={"leanstral": "exact-test-model"},
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    # Absolute case deadlines legitimately shave a few milliseconds from the
    # measured 120 s provider cap.
    leanstral = _strict_leanstral_artifact(
        base_request,
        compiled,
        draft_overrides={"timeout_ms": 119_999},
    )
    leanstral_identity = {
        "endpoint": "http://127.0.0.1:8080/v1",
        "provider": "leanstral_local",
        "model": "exact-test-model",
    }
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_leanstral_identity=leanstral_identity,
    )
    fake = _FakeSupervisor(tmp_path)
    runner._supervisor = fake
    request = adapters.StageRequest(
        run_id="runtime-kernel",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A9",
        input_data=value,
        requested_identity={"kernel": "lean"},
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler, leanstral),
        invocation_index=2,
    )

    output = runner(request)

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.kernel_accepted
    assert output.kernel_receipt_sha256 == output.data["receipt_sha256"]
    assert output.data["independent"] is True
    assert output.data["candidate_artifact_sha256"] == leanstral.digest
    assert output.data["active_process_count"] == 0
    runner.close()
    assert fake.closed

    rejected_root = tmp_path / "rejected"
    rejected_root.mkdir()
    rejected_runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        rejected_root / "state",
        expected_leanstral_identity=leanstral_identity,
    )
    rejected_runner._supervisor = _FakeSupervisor(
        rejected_root, returncode=1
    )
    rejected = rejected_runner(request)
    assert rejected.status is contracts.StageStatus.FAILED
    assert not rejected.kernel_accepted
    assert rejected.failure_code is contracts.FailureCode.KERNEL_REJECTION
    assert rejected.data["accepted"] is False
    rejected_runner.close()


def test_independent_kernel_accepts_exact_hammer_candidate(
    tmp_path: Path,
) -> None:
    value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
    )
    _, translation, compiler = _strict_compiler_artifact(value)
    assert translation is not None
    base_request = adapters.StageRequest(
        run_id="runtime-hammer-kernel",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data=value,
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    hammer = _strict_hammer_artifact(base_request, translation)
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_hammer_identity={
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": "/test/cvc5",
        },
    )
    runner._supervisor = _FakeSupervisor(
        tmp_path,
        expected_proof=translation.hammer_proof_text,
    )

    output = runner(
        adapters.StageRequest(
            run_id=base_request.run_id,
            case_id=base_request.case_id,
            case_manifest_sha256=base_request.case_manifest_sha256,
            variant_id="A2",
            input_data=value,
            requested_identity={"kernel": "lean"},
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler, hammer),
            invocation_index=2,
        )
    )

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.kernel_accepted
    assert output.data["candidate_artifact_sha256"] == hammer.digest


def test_kernel_rejects_hammer_candidate_copied_from_another_case(
    tmp_path: Path,
) -> None:
    copied_value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
        obligation_id="copied-obligation",
    )
    actual_value = _reviewed_entailment(
        (
            "Every sailor is ready. Bea is a sailor. "
            "Therefore Bea is ready."
        ),
        "ready",
        obligation_id="actual-obligation",
    )
    _, copied_translation, copied_compiler = _strict_compiler_artifact(
        copied_value
    )
    _, _, actual_compiler = _strict_compiler_artifact(actual_value)
    assert copied_translation is not None
    copied_request = adapters.StageRequest(
        run_id="runtime-hammer-copied",
        case_id="copied-case",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data=copied_value,
        environment_sha256="b" * 64,
        upstream_artifacts=(copied_compiler,),
        invocation_index=1,
    )
    copied_hammer = _strict_hammer_artifact(
        copied_request, copied_translation
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_hammer_identity={
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": "/test/cvc5",
        },
    )

    output = runner(
        adapters.StageRequest(
            run_id="runtime-hammer-copied",
            case_id="actual-case",
            case_manifest_sha256="a" * 64,
            variant_id="A2",
            input_data=actual_value,
            environment_sha256="b" * 64,
            upstream_artifacts=(actual_compiler, copied_hammer),
            invocation_index=2,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert (
        output.failure_code
        is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert output.data["reason"] == "proof_candidate_binding_invalid"
    assert runner._supervisor is None


@pytest.mark.parametrize(
    ("field_name", "tampered_value"),
    [
        ("translation_sha256", "0" * 64),
        ("solver_input_sha256", "1" * 64),
    ],
)
def test_kernel_rejects_tampered_hammer_receipt_before_lean(
    tmp_path: Path,
    field_name: str,
    tampered_value: str,
) -> None:
    value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
    )
    _, translation, compiler = _strict_compiler_artifact(value)
    assert translation is not None
    base_request = adapters.StageRequest(
        run_id="runtime-hammer-tampered",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data=value,
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    hammer = _strict_hammer_artifact(
        base_request,
        translation,
        overrides={field_name: tampered_value},
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_hammer_identity={
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": "/test/cvc5",
        },
    )

    output = runner(
        adapters.StageRequest(
            run_id=base_request.run_id,
            case_id=base_request.case_id,
            case_manifest_sha256=base_request.case_manifest_sha256,
            variant_id="A2",
            input_data=value,
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler, hammer),
            invocation_index=2,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert output.data["reason"] == "proof_candidate_binding_invalid"
    assert runner._supervisor is None


def test_kernel_rejects_leanstral_candidate_copied_from_another_case(
    tmp_path: Path,
) -> None:
    copied_value = {
        "text": "copied target",
        "obligation_id": "copied-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "copied-target",
        },
    }
    actual_value = {
        "text": "actual target",
        "obligation_id": "actual-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "actual-target",
        },
    }
    copied_compiled, _, copied_compiler = _strict_compiler_artifact(
        copied_value
    )
    _, _, actual_compiler = _strict_compiler_artifact(actual_value)
    copied_request = adapters.StageRequest(
        run_id="runtime-leanstral-copied",
        case_id="copied-case",
        case_manifest_sha256="a" * 64,
        variant_id="A3",
        input_data=copied_value,
        environment_sha256="b" * 64,
        upstream_artifacts=(copied_compiler,),
        invocation_index=1,
    )
    copied_leanstral = _strict_leanstral_artifact(
        copied_request, copied_compiled
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_leanstral_identity={
            "endpoint": "http://127.0.0.1:8080/v1",
            "provider": "leanstral_local",
            "model": "exact-test-model",
        },
    )

    output = runner(
        adapters.StageRequest(
            run_id="runtime-leanstral-copied",
            case_id="actual-case",
            case_manifest_sha256="a" * 64,
            variant_id="A3",
            input_data=actual_value,
            environment_sha256="b" * 64,
            upstream_artifacts=(actual_compiler, copied_leanstral),
            invocation_index=2,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert (
        output.failure_code
        is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert output.data["reason"] == "proof_candidate_binding_invalid"
    assert runner._supervisor is None


@pytest.mark.parametrize(
    ("boundary_overrides", "draft_overrides"),
    [
        ({"normalized_proposal_sha256": "0" * 64}, None),
        ({"endpoint": "http://127.0.0.1:9999/v1"}, None),
        (None, {"timeout_ms": 300_000}),
    ],
)
def test_kernel_rejects_tampered_leanstral_receipt_before_lean(
    tmp_path: Path,
    boundary_overrides: dict[str, object] | None,
    draft_overrides: dict[str, object] | None,
) -> None:
    value = {
        "text": "target",
        "obligation_id": "obl-1",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "target",
        },
    }
    compiled, _, compiler = _strict_compiler_artifact(value)
    base_request = adapters.StageRequest(
        run_id="runtime-leanstral-tampered",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A3",
        input_data=value,
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    leanstral = _strict_leanstral_artifact(
        base_request,
        compiled,
        boundary_overrides=boundary_overrides,
        draft_overrides=draft_overrides,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
        expected_leanstral_identity={
            "endpoint": "http://127.0.0.1:8080/v1",
            "provider": "leanstral_local",
            "model": "exact-test-model",
        },
    )

    output = runner(
        adapters.StageRequest(
            run_id=base_request.run_id,
            case_id=base_request.case_id,
            case_manifest_sha256=base_request.case_manifest_sha256,
            variant_id="A3",
            input_data=value,
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler, leanstral),
            invocation_index=2,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert output.data["reason"] == "proof_candidate_binding_invalid"
    assert runner._supervisor is None


@pytest.mark.parametrize(
    ("text", "target", "shape", "proof_text"),
    [
        (
            (
                "Every archivist is trained. Ada is an archivist. "
                "Therefore Ada is trained."
            ),
            "trained",
            "direct_unary_entailment",
            "exact rule witness fact",
        ),
        (
            (
                "Every red item is warm. Every warm item is safe. "
                "Object R is red. Therefore object R is safe."
            ),
            "safe",
            "two_step_unary_chain",
            "exact second_rule witness (first_rule witness fact)",
        ),
    ],
)
def test_a1_compiler_candidate_reaches_independent_kernel(
    tmp_path: Path,
    text: str,
    target: str,
    shape: str,
    proof_text: str,
) -> None:
    value = _reviewed_entailment(text, target)
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    translation = runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is not None and translation.native_proof_text is not None
    assert translation.shape == shape
    assert translation.native_proof_text == proof_text
    native_candidate = {
        "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
        "translation_sha256": translation.digest,
        "obligation_sha256": compiled.obligation_sha256,
        "source_sha256": translation.source_sha256,
        "derivation": translation.shape,
        "certificate": translation.native_proof_text,
        "authoritative": False,
        "requires_independent_kernel": True,
    }
    compiler = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
            "native_proof_candidate": native_candidate,
        },
        None,
        {"backend": "compiler"},
        0,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
    )
    runner._supervisor = _FakeSupervisor(
        tmp_path,
        expected_proof=translation.native_proof_text,
    )
    output = runner(
        adapters.StageRequest(
            run_id="runtime-a1-kernel",
            case_id="case-1",
            case_manifest_sha256="a" * 64,
            variant_id="A1",
            input_data=value,
            requested_identity={"kernel": "lean"},
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler,),
            invocation_index=1,
        )
    )

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.kernel_accepted
    assert output.kernel_receipt_sha256 is not None


@pytest.mark.parametrize(
    "tamper",
    [
        lambda candidate: {
            **candidate,
            "schema": "ipfs-datasets.logic-pipeline-benchmark.wrong-candidate.v1",
        },
        lambda candidate: {**candidate, "source_sha256": "0" * 64},
        lambda candidate: {
            **candidate,
            "translation_sha256": "1" * 64,
        },
    ],
)
def test_a1_kernel_rejects_tampered_compiler_candidate_before_lean(
    tmp_path: Path,
    tamper: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
    )
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    translation = runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is not None and translation.native_proof_text is not None
    candidate = {
        "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
        "translation_sha256": translation.digest,
        "obligation_sha256": compiled.obligation_sha256,
        "source_sha256": translation.source_sha256,
        "derivation": translation.shape,
        "certificate": translation.native_proof_text,
        "authoritative": False,
        "requires_independent_kernel": True,
    }
    compiler = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
            "native_proof_candidate": tamper(candidate),
        },
        None,
        {"backend": "compiler"},
        0,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
    )
    output = runner(
        adapters.StageRequest(
            run_id="runtime-a1-tamper",
            case_id="case-1",
            case_manifest_sha256="a" * 64,
            variant_id="A1",
            input_data=value,
            requested_identity={"kernel": "lean"},
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler,),
            invocation_index=1,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert output.kernel_accepted is False
    assert output.failure_code is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    assert output.data["accepted"] is False
    assert output.data["reason"] == "compiler_binding_invalid"
    assert runner._supervisor is None


def test_a1_kernel_rejects_compiler_artifact_copied_from_another_case(
    tmp_path: Path,
) -> None:
    copied_value = _reviewed_entailment(
        (
            "Every archivist is trained. Ada is an archivist. "
            "Therefore Ada is trained."
        ),
        "trained",
        obligation_id="copied-obligation",
    )
    actual_value = {
        "text": (
            "A licensed carrier must file a report. Mira is a licensed carrier. "
            "Therefore Mira is obligated to file a report."
        ),
        "obligation_id": "actual-deontic-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "deontic",
            "target": "obligated",
        },
    }
    compiled = runtime.compile_reviewed_obligation(copied_value)
    assert compiled is not None
    translation = runtime._entailment_translation(
        copied_value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is not None and translation.native_proof_text is not None
    compiler = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
            "native_proof_candidate": {
                "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
                "translation_sha256": translation.digest,
                "obligation_sha256": compiled.obligation_sha256,
                "source_sha256": translation.source_sha256,
                "derivation": translation.shape,
                "certificate": translation.native_proof_text,
                "authoritative": False,
                "requires_independent_kernel": True,
            },
        },
        None,
        {"backend": "copied-compiler"},
        0,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
    )
    output = runner(
        adapters.StageRequest(
            run_id="runtime-a1-copied-artifact",
            case_id="actual-deontic-case",
            case_manifest_sha256="a" * 64,
            variant_id="A1",
            input_data=actual_value,
            requested_identity={"kernel": "lean"},
            environment_sha256="b" * 64,
            upstream_artifacts=(compiler,),
            invocation_index=1,
        )
    )

    assert output.status is contracts.StageStatus.FAILED
    assert output.failure_code is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    assert output.kernel_accepted is False
    assert "current request input" in str(output.failure_detail)
    assert runner._supervisor is None


def test_a2_hammer_emits_candidate_only_after_unsat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _reviewed_entailment(
        (
            "Every red item is warm. Every warm item is safe. "
            "Object R is red. Therefore object R is safe."
        ),
        "safe",
    )
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    translation = runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is not None
    compiler = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
        },
        None,
        {"backend": "compiler"},
        0,
    )
    request = adapters.StageRequest(
        run_id="runtime-a2-hammer",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data=value,
        requested_identity={"hammer": "cvc5"},
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    record = capabilities.CapabilityRecord(
        capabilities.CapabilityKind.HAMMER,
        capabilities.CapabilityStatus.AVAILABLE,
        {
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": "/test/cvc5",
        },
        ("integration-test",),
    )
    observed_inputs: list[bytes] = []

    def solver(
        _arguments: object,
        **kwargs: object,
    ) -> capabilities.BoundedProcessResult:
        observed_inputs.append(kwargs["input_bytes"])
        return capabilities.BoundedProcessResult(
            arguments=("/test/cvc5", "--lang=smt2"),
            returncode=0,
            stdout="unsat\n",
            stderr="",
            timed_out=False,
            process_group_reaped=True,
        )

    monkeypatch.setattr(runtime, "run_bounded_process_group", solver)
    output = runtime._hammer_live_handler(record)(request)

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.data["solver_status"] == "unsat"
    assert output.data["candidate_created"] is True
    assert output.data["proof_text"] == translation.hammer_proof_text
    assert observed_inputs == [translation.smt2_problem.encode("utf-8")]

    def countermodel(
        _arguments: object,
        **_kwargs: object,
    ) -> capabilities.BoundedProcessResult:
        return capabilities.BoundedProcessResult(
            arguments=("/test/cvc5", "--lang=smt2"),
            returncode=0,
            stdout="sat\n",
            stderr="",
            timed_out=False,
            process_group_reaped=True,
        )

    monkeypatch.setattr(runtime, "run_bounded_process_group", countermodel)
    rejected = runtime._hammer_live_handler(record)(request)
    assert rejected.data["solver_status"] == "sat"
    assert rejected.data["candidate_created"] is False
    assert rejected.data["proof_text"] is None
