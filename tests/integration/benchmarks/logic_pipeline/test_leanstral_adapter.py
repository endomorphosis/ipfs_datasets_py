"""Integration evidence for the bounded, draft-only Leanstral adapter."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime


SHA_A = "a" * 64
SHA_B = "b" * 64


def _request(**input_data: object) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id="leanstral-run-1",
        case_id="leanstral-case-1",
        case_manifest_sha256=SHA_A,
        input_data={
            "obligation_id": "obl-identity",
            "prompt": "Prove the identity obligation.",
            **input_data,
        },
        requested_identity={"provider": "leanstral_local", "model": "Leanstral"},
        environment_sha256=SHA_B,
    )


def _draft(text: str = "exact rfl") -> dict[str, object]:
    return {
        "schema_version": adapters.LEANSTRAL_DRAFT_SCHEMA,
        "artifact_id": "leanstral-draft-test-1",
        "artifact_kind": "llm_output",
        "stage": "model_draft",
        "draft_text": text,
        "proof_text": text,
        "request_id": "provider-request-1",
        "llm_provider": "leanstral_local",
        "model": "Leanstral",
        "obligation_ids": ["obl-identity"],
        "resource_class": "model",
        "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
    }


def _run(handler, request: adapters.StageRequest | None = None):
    return adapters.LeanstralAdapter(handler).run(request or _request())


def test_objective_receipt_and_successful_draft_are_explicitly_unverified() -> None:
    assert adapters.HSSLEV0342A4C() == (
        "Leanstral proof drafts use strict schemas and one bounded unverified repair"
    )
    record = _run(lambda request: _draft())

    assert record.stage is contracts.StageName.LEANSTRAL
    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["schema"] == adapters.LEANSTRAL_EVIDENCE_SCHEMA
    assert record.data["mode"] == "synthesis"
    assert record.data["repair_attempts"] == 0
    assert record.data["obligation_id"] == "obl-identity"
    assert record.data["trust"] == {
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
    }
    assert record.kernel_accepted is False
    assert record.kernel_receipt_sha256 is None
    assert record.data["resource_classes"] == {
        "model_inference": "model",
        "kernel_check": "kernel",
    }
    assert contracts.StageRecord.from_dict(record.to_dict()).digest == record.digest


def test_repair_is_one_explicit_attempt_and_preserves_failure_context() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        assert isinstance(request.input_data, dict)
        seen.append(request.input_data)
        return _draft("simp")

    record = _run(
        handler,
        _request(
            repair_attempt=1,
            repair={
                "failed_draft": "by exact wrong_lemma",
                "failure": "unknown constant wrong_lemma",
            },
        ),
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["mode"] == "repair"
    assert record.data["repair_attempts"] == 1
    assert len(seen) == 1
    assert seen[0]["max_repair_attempts"] == 1
    assert seen[0]["compact_failures"] == [
        {"message": "unknown constant wrong_lemma"}
    ]


def test_frozen_case_text_is_the_prompt_at_the_leanstral_boundary() -> None:
    seen: list[dict[str, object]] = []
    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        assert isinstance(request.input_data, dict)
        seen.append(request.input_data)
        return _draft()

    record = _run(handler, _request(prompt=None, text=source_text))

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(seen) == 1
    assert seen[0]["prompt"] == source_text
    assert seen[0]["text"] == source_text
    assert seen[0]["obligation_id"] == "obl-identity"


def test_frozen_case_text_crosses_the_supervisor_provider_contract() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    seen_prompts: list[str] = []
    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    provider = LeanstralProofProvider(
        llm_generate=lambda prompt, **_kwargs: (
            seen_prompts.append(prompt) or "exact h"
        )
    )

    record = adapters.LeanstralAdapter(provider=provider).run(
        _request(prompt=None, text=source_text)
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert seen_prompts == [source_text]
    assert record.data["draft"]["schema_version"] == adapters.LEANSTRAL_DRAFT_SCHEMA
    assert record.data["draft"]["obligation_ids"] == ("obl-identity",)
    assert record.data["trust"]["assurance"] == "unverified"
    assert record.kernel_accepted is False


def test_a3_fallback_binds_the_compiler_theorem_and_structured_schema() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    compiled = runtime.compile_reviewed_obligation(
        {
            "text": source_text,
            "obligation_id": "obl-identity",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={"compiled_obligation": compiled.to_dict()},
        output_sha256=None,
        effective_identity={"entrypoint": "test-compiler"},
        invocation_index=0,
    )
    seen_prompts: list[dict[str, object]] = []

    def generate(prompt: str, **_kwargs: object) -> str:
        structured = json.loads(prompt)
        seen_prompts.append(structured)
        theorem = structured["fixed_theorem"]
        return json.dumps(
            {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor."
                    "leanstral-proof-proposal@1"
                ),
                "theorem_id": theorem["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "exact rule witness fact",
            }
        )

    request = replace(
        _request(prompt=None, text=source_text),
        variant_id="A3",
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    record = adapters.LeanstralAdapter(
        provider=LeanstralProofProvider(llm_generate=generate)
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(seen_prompts) == 1
    fixed = seen_prompts[0]["fixed_theorem"]
    assert "translation:direct_unary_entailment" in compiled.source_template
    assert fixed["obligation_id"] == "obl-identity"
    assert fixed["declaration_name"] == compiled.theorem_name
    assert [item.split()[0] for item in fixed["assumptions"]] == [
        "(witness",
        "(rule",
        "(fact",
    ]
    assert fixed["conclusion"]
    assert fixed["conclusion"] in compiled.source_template
    assert fixed["canonical_source_digest"] == (
        f"sha256:{compiled.source_template_sha256}"
    )
    assert seen_prompts[0]["output_schema"]["schema"] == (
        "ipfs_accelerate_py.agent_supervisor.leanstral-proof-proposal@1"
    )
    assert record.data["draft"]["context_capsule_id"].startswith(
        "proof-context:sha256:"
    )
    assert record.data["draft"]["proof_text"] == "exact rule witness fact"
    rendered = compiled.render(record.data["draft"]["proof_text"])
    assert "by\n  exact rule witness fact" in rendered
    assert "by\n  by" not in rendered
    assert record.kernel_accepted is False


def test_semantic_confidence_numbers_cross_strict_provider_boundary() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    compiled = runtime.compile_reviewed_obligation(
        {
            "text": source_text,
            "obligation_id": "obl-identity",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={"compiled_obligation": compiled.to_dict()},
        output_sha256=None,
        effective_identity={"entrypoint": "test-compiler"},
        invocation_index=0,
    )
    spacy = adapters.StageArtifact(
        stage=contracts.StageName.SPACY,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.SPACY_EVIDENCE_SCHEMA,
            "semantic_roles": [
                {
                    "frame_id": "role-1",
                    "sentence": "Ada is trained.",
                    "predicate": "train",
                    "predicate_span": [7, 14],
                    "arguments": [
                        {
                            "role": "Agent",
                            "text": "Ada",
                            "span": [0, 3],
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                    "source": "spacy",
                }
            ],
        },
        output_sha256=None,
        effective_identity={
            "graph_invoked": True,
            "graph_invocation_index": 1,
        },
        invocation_index=1,
    )
    max_text = "x" * 77
    candidate_ir = {
        "propositions": [
            f"{index:02d}-{max_text}" for index in range(12)
        ]
    }
    symai = adapters.StageArtifact(
        stage=contracts.StageName.SYMAI,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.SYMAI_EVIDENCE_SCHEMA,
            "candidate_ir": candidate_ir,
            "candidate_ir_sha256": hashlib.sha256(
                contracts.canonical_json(candidate_ir).encode("utf-8")
            ).hexdigest(),
            "normalized_predicates": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "quantifiers": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "entities": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "ambiguity_flags": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "confidence": 0.9,
            "validation_errors": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "assurance": {
                "semantic_hypothesis": True,
                "authoritative": False,
            },
        },
        output_sha256=None,
        effective_identity={
            "graph_invoked": True,
            "graph_invocation_index": 2,
        },
        invocation_index=2,
    )
    prompts: list[dict[str, object]] = []
    prompt_texts: list[str] = []

    def generate(prompt: str, **_kwargs: object) -> str:
        structured = json.loads(prompt)
        prompt_texts.append(prompt)
        prompts.append(structured)
        return json.dumps(
            {
                "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
                "theorem_id": structured["fixed_theorem"]["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "exact rule witness fact",
            }
        )

    request = replace(
        _request(prompt=None, text=source_text),
        variant_id="A4",
        upstream_artifacts=(compiler, spacy, symai),
        invocation_index=3,
    )
    source_context = adapters.build_upstream_semantic_context(request)
    payload, _obligation_id, _repair_attempt = adapters._leanstral_input(
        request,
        adapters.LeanstralAdapterConfig(),
    )
    record = adapters.LeanstralAdapter(
        provider=LeanstralProofProvider(llm_generate=generate)
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(prompts) == 1
    fields = payload["context_capsule"]["untrusted_suggestions"][0]["fields"]
    assert fields["schema"] == (
        adapters.LEANSTRAL_STRICT_SEMANTIC_CONTEXT_SCHEMA
    )
    assert fields["source_semantic_context_sha256"] == (
        source_context["context_sha256"]
    )
    encoded_role = fields["semantic_context"]["artifacts"][0]["evidence"][
        "semantic_roles"
    ][0]
    assert encoded_role["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.8",
    }
    assert encoded_role["arguments"][0]["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.8",
    }
    encoded_symai = fields["semantic_context"]["artifacts"][1]["evidence"]
    assert len(encoded_symai["normalized_predicates"]) == 24
    assert encoded_symai["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.9",
    }
    final_hints = prompts[0]["untrusted_semantic_hints"]
    assert len(final_hints) == 1
    hint = final_hints[0]
    assert hint["semantic_context"] == fields
    assert hint["trust"] == "untrusted_suggestion"
    assert hint["checked_evidence"] is False
    assert hint["authoritative"] is False
    assert hint["usable_as_premise"] is False
    assert hint["usable_as_proof_evidence"] is False
    assert hint["usable_as_failure_evidence"] is False
    assert hint["content_sha256"] == (
        "sha256:"
        + hashlib.sha256(
            contracts.canonical_json(fields).encode("utf-8")
        ).hexdigest()
    )
    assert len(contracts.canonical_json(hint).encode("utf-8")) > 10_002
    assert prompts[0]["semantic_hint_policy"] == {
        "semantic_guidance_only": True,
        "authoritative": False,
        "usable_as_premise": False,
        "usable_as_trusted_receipt": False,
        "usable_as_proof_evidence": False,
        "usable_as_failure_evidence": False,
    }
    final_prompt_sha256 = hashlib.sha256(
        prompt_texts[0].encode("utf-8")
    ).hexdigest()
    assert record.data["draft"]["prompt_sha256"] == final_prompt_sha256
    assert record.data["draft"]["context_capsule_id"] == (
        payload["context_capsule"]["capsule_id"]
    )


def test_non_corpus_runtime_readiness_smoke_uses_the_same_strict_boundary() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
        LeanstralProofProviderConfig,
    )

    calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def generate(prompt: str, **kwargs: object) -> str:
        structured = json.loads(prompt)
        calls.append((structured, kwargs))
        return json.dumps(
            {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor."
                    "leanstral-proof-proposal@1"
                ),
                "theorem_id": structured["fixed_theorem"]["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "rfl",
            }
        )

    provider = LeanstralProofProvider(
        LeanstralProofProviderConfig(
            llm_provider="leanstral_local",
            model="exact-test-model",
        ),
        llm_generate=generate,
    )
    record = adapters.run_leanstral_runtime_readiness_smoke(
        provider,
        provider_identity={
            "provider": "leanstral_local",
            "model": "exact-test-model",
        },
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert prompt["fixed_theorem"]["obligation_id"] == (
        "leanstral-runtime-smoke-obligation"
    )
    assert kwargs["provider"] == "leanstral_local"
    assert kwargs["model_name"] == "exact-test-model"
    assert kwargs["allow_local_fallback"] is False
    assert 0 < kwargs["timeout"] <= adapters.LEANSTRAL_MEASURED_TIMEOUT_SECONDS
    assert kwargs["max_new_tokens"] == (
        adapters.LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    )
    assert record.data["draft"]["context_capsule_id"].startswith(
        "proof-context:sha256:"
    )
    assert record.data["draft"]["model"] == "exact-test-model"
    assert record.kernel_accepted is False


def test_measured_supervisor_request_binds_budget_and_absolute_deadline() -> None:
    requests: list[object] = []

    class Provider:
        def prove(self, request: object) -> dict[str, object]:
            requests.append(request)
            return _draft()

    config = adapters.LeanstralAdapterConfig(
        model_timeout_seconds=17.0,
        model_token_limit=321,
    )
    case_request = _request()
    expected_request_id = "leanstral-" + hashlib.sha256(
        (
            f"{case_request.run_id}:{case_request.case_id}:"
            f"{case_request.input_sha256}:0"
        ).encode("utf-8")
    ).hexdigest()[:48]
    before_ms = int(time.time() * 1_000)
    record = adapters.LeanstralAdapter(
        provider=Provider(),
        config=config,
    ).run(case_request)
    after_ms = int(time.time() * 1_000)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(requests) == 1
    provider_request = requests[0]
    assert provider_request.resource_budget.wall_time_ms == 17_000
    assert provider_request.resource_budget.model_token_limit == 321
    assert provider_request.resource_budget.max_output_bytes == (
        adapters.LEANSTRAL_MAX_DRAFT_BYTES
    )
    assert provider_request.request_id == expected_request_id
    assert before_ms + 17_000 <= provider_request.deadline_unix_ms
    assert provider_request.deadline_unix_ms <= after_ms + 17_000
    assert provider_request.network_allowed is False


def test_case_deadline_caps_measured_leanstral_invocation() -> None:
    requests: list[object] = []

    class Provider:
        def prove(self, request: object) -> dict[str, object]:
            requests.append(request)
            return _draft()

    case_deadline_unix_ms = int(time.time() * 1_000) + 500
    record = adapters.LeanstralAdapter(
        provider=Provider(),
        config=adapters.LeanstralAdapterConfig(
            model_timeout_seconds=17.0,
            model_token_limit=321,
        ),
    ).run(
        replace(
            _request(),
            deadline_unix_ms=case_deadline_unix_ms,
        )
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(requests) == 1
    provider_request = requests[0]
    assert provider_request.deadline_unix_ms == case_deadline_unix_ms
    assert 1 <= provider_request.resource_budget.wall_time_ms <= 500
    assert provider_request.resource_budget.model_token_limit == 321


def test_expired_absolute_deadline_cancels_before_model_generation() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    model_calls = 0

    def generate(_prompt: str, **_kwargs: object) -> str:
        nonlocal model_calls
        model_calls += 1
        return "exact rfl"

    delegate = LeanstralProofProvider(llm_generate=generate)

    class DelayedProvider:
        def prove(self, request: object) -> object:
            time.sleep(0.02)
            return delegate.prove(request)

    record = adapters.LeanstralAdapter(
        provider=DelayedProvider(),
        config=adapters.LeanstralAdapterConfig(
            model_timeout_seconds=0.005,
            model_token_limit=64,
        ),
    ).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is (
        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert "timed_out" in str(record.failure_detail)
    assert model_calls == 0


def test_strict_provider_request_failure_is_safe_and_pre_generation() -> None:
    provider_calls = 0

    class Provider:
        def prove(self, _request: object) -> dict[str, object]:
            nonlocal provider_calls
            provider_calls += 1
            return _draft()

    record = adapters.LeanstralAdapter(provider=Provider()).run(
        _request(context_capsule={"confidence": 0.8})
    )

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is (
        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.failure_detail == (
        "Leanstral supervisor rejected the strict provider request"
    )
    assert record.telemetry.model_calls == 0
    assert provider_calls == 0


def test_request_isolated_provider_does_not_reuse_delegate_state() -> None:
    instances: list[object] = []

    class StatefulProvider:
        def __init__(self) -> None:
            self.calls = 0
            instances.append(self)

        def prove(self, _request: object) -> int:
            self.calls += 1
            return self.calls

    provider = adapters._RequestIsolatedLeanstralProvider(StatefulProvider)

    assert provider.prove(object()) == 1
    assert provider.prove(object()) == 1
    assert len(instances) == 2


def test_strict_live_generator_pins_endpoint_model_and_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "http://127.0.0.1:8080/v1"
    provider = "leanstral_local"
    model = "exact-test-model"
    calls: list[tuple[str, bytes | None]] = []
    timeouts: list[float] = []
    monotonic = iter((100.0, 101.0, 105.0))

    class Response:
        def __init__(self, value: object) -> None:
            self._raw = json.dumps(value).encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, maximum: int) -> bytes:
            return self._raw[:maximum]

    raw_output = json.dumps(
        {
            "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "theorem_id": "hssl_test",
            "proposal_kind": "proof",
            "proof_text": "by\n  rfl",
        }
    )
    expected_output = {
        "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "theorem_id": "hssl_test",
        "proposal_kind": "proof",
        "proof_text": "rfl",
    }

    def urlopen(request: object, *, timeout: float) -> Response:
        timeouts.append(timeout)
        calls.append((request.full_url, request.data))
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": model}]})
        payload = json.loads(request.data.decode("utf-8"))
        schema = payload["response_format"]["json_schema"]["schema"]
        assert payload["model"] == model
        assert payload["stream"] is False
        assert payload["seed"] == 0
        assert payload["messages"][0]["role"] == "system"
        assert "tactic body" in payload["messages"][0]["content"]
        assert "already in scope" in payload["messages"][0]["content"]
        assert "explanatory comments" in payload["messages"][0]["content"]
        assert payload["stop"] == [
            "<|tool_call_end|>",
            "<|im_end|>",
            "<|im_start|>",
        ]
        assert schema["properties"]["theorem_id"] == {"const": "hssl_test"}
        assert schema["properties"]["schema"] == {
            "const": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
        }
        return Response(
            {
                "model": model,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": raw_output},
                    }
                ],
            }
        )

    monkeypatch.setattr(adapters.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(adapters.time, "monotonic", lambda: next(monotonic))
    generate = adapters.create_pinned_leanstral_llm_generate(
        endpoint=endpoint,
        provider=provider,
        model=model,
    )
    prompt = json.dumps(
        {
            "fixed_theorem": {"theorem_id": "hssl_test"},
            "output_schema": {
                "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
            },
        }
    )

    generated = generate(
        prompt,
        provider=provider,
        model_name=model,
        timeout=30.0,
        max_new_tokens=64,
        allow_local_fallback=False,
        disable_model_retry=True,
        temperature=0.0,
    )
    assert json.loads(generated) == expected_output
    receipt = generate.consume_receipt(
        hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    )
    assert receipt is not None
    assert receipt["schema"] == adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA
    assert receipt["endpoint"] == endpoint
    assert receipt["requested_model"] == model
    assert receipt["response_model"] == model
    assert receipt["normalization"] == "strip_single_leading_by"
    assert receipt["raw_model_content_sha256"] == hashlib.sha256(
        raw_output.encode("utf-8")
    ).hexdigest()
    assert receipt["normalized_proposal_sha256"] == hashlib.sha256(
        generated.encode("utf-8")
    ).hexdigest()
    assert calls == [
        (f"{endpoint}/models", None),
        (f"{endpoint}/chat/completions", calls[1][1]),
    ]
    assert timeouts == [29.0, 25.0]


def _audited_provider_draft(
    prompt_sha256: str,
    proof_text: str,
) -> dict[str, object]:
    return {
        "proposal_schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "theorem_id": "hssl_test",
        "proposal_kind": "proof",
        "draft_text": proof_text,
        "proof_text": proof_text,
        "prompt_sha256": prompt_sha256,
        "metadata": {},
    }


def _generation_receipt_for_draft(
    prompt_sha256: str,
    proof_text: str,
) -> dict[str, object]:
    normalized = json.dumps(
        {
            "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "theorem_id": "hssl_test",
            "proposal_kind": "proof",
            "proof_text": proof_text,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema": adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
        "prompt_sha256": prompt_sha256,
        "normalized_proposal_sha256": hashlib.sha256(normalized).hexdigest(),
        "normalized_proposal_bytes": len(normalized),
    }


def test_audited_provider_selects_exact_receipt_for_same_prompt() -> None:
    prompt_sha256 = hashlib.sha256(b"same prompt").hexdigest()
    generator = adapters._PinnedLeanstralGenerate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )
    calls = iter(("exact first", "exact second"))

    class Delegate:
        def prove(self, _request: object) -> dict[str, object]:
            proof_text = next(calls)
            receipt = _generation_receipt_for_draft(
                prompt_sha256, proof_text
            )
            generator._receipt_local.pending = (prompt_sha256, receipt)
            return _audited_provider_draft(prompt_sha256, proof_text)

    audited = adapters._AuditedLeanstralProvider(Delegate(), generator)
    first = audited.prove(object())
    second = audited.prove(object())

    assert first["metadata"]["benchmark_generation_boundary"] == (
        _generation_receipt_for_draft(prompt_sha256, "exact first")
    )
    assert second["metadata"]["benchmark_generation_boundary"] == (
        _generation_receipt_for_draft(prompt_sha256, "exact second")
    )
    assert generator.consume_receipt(prompt_sha256) is None


@pytest.mark.parametrize(
    "tamper",
    [
        lambda receipt: {**receipt, "prompt_sha256": "0" * 64},
        lambda receipt: {
            **receipt,
            "normalized_proposal_bytes": (
                int(receipt["normalized_proposal_bytes"]) + 1
            ),
        },
    ],
)
def test_audited_provider_rejects_tampered_generation_receipt(
    tamper,
) -> None:
    prompt_sha256 = hashlib.sha256(b"fixed prompt").hexdigest()
    draft = _audited_provider_draft(prompt_sha256, "exact target")
    generator = adapters._PinnedLeanstralGenerate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )
    receipt = tamper(
        _generation_receipt_for_draft(prompt_sha256, "exact target")
    )
    generator._receipt_local.pending = (prompt_sha256, receipt)

    class Delegate:
        @staticmethod
        def prove(_request: object) -> dict[str, object]:
            return draft

    audited = adapters._AuditedLeanstralProvider(Delegate(), generator)
    with pytest.raises(
        adapters.LeanstralAdapterContractError,
        match="does not match the returned draft",
    ):
        audited.prove(object())
    assert generator.consume_receipt(prompt_sha256) is None


def test_strict_live_generator_rejects_model_substitution_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace()

    monkeypatch.setattr(adapters.urllib.request, "urlopen", urlopen)
    generate = adapters.create_pinned_leanstral_llm_generate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )

    with pytest.raises(
        adapters.LeanstralAdapterContractError,
        match="drifted from the frozen identity",
    ):
        generate(
            json.dumps(
                {
                    "fixed_theorem": {"theorem_id": "hssl_test"},
                    "output_schema": {
                        "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
                    },
                }
            ),
            provider="leanstral_local",
            model_name="substituted-model",
            timeout=30.0,
            max_new_tokens=64,
            allow_local_fallback=False,
            disable_model_retry=True,
            temperature=0.0,
        )
    assert called is False


@pytest.mark.parametrize(
    "mutator",
    [
        lambda draft: draft | {"schema_version": "wrong-schema"},
        lambda draft: draft | {"obligation_ids": ["other-obligation"]},
        lambda draft: draft | {"draft_text": "exact sorry", "proof_text": "exact sorry"},
        lambda draft: draft | {"draft_text": "by exact rfl", "proof_text": "by exact rfl"},
        lambda draft: draft
        | {
            "draft_text": "import Mathlib\ntheorem x : True := by\n  trivial",
            "proof_text": "import Mathlib\ntheorem x : True := by\n  trivial",
        },
        lambda draft: draft
        | {
            "draft_text": "```lean\nexact rfl\n```",
            "proof_text": "```lean\nexact rfl\n```",
        },
        lambda draft: draft | {"authoritative": True},
    ],
)
def test_malformed_forbidden_or_authoritative_model_output_fails_closed(mutator) -> None:
    record = _run(lambda _request: mutator(_draft()))

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.output_sha256 is None
    assert record.kernel_accepted is False


def test_nested_by_inside_a_tactic_body_is_not_rejected() -> None:
    text = "have h : True := by\n  trivial\nexact h"
    record = _run(lambda _request: _draft(text))

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["draft"]["proof_text"] == text


def test_timeout_and_unavailable_backend_are_distinct_explicit_outcomes() -> None:
    timed_out = _run(lambda _request: (_ for _ in ()).throw(TimeoutError("deadline")))
    assert timed_out.status is contracts.StageStatus.FAILED
    assert (
        timed_out.failure_code
        is contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )

    unavailable = _run(
        lambda _request: (_ for _ in ()).throw(
            ImportError("leanstral provider is not installed")
        )
    )
    assert unavailable.status is contracts.StageStatus.UNAVAILABLE
    assert unavailable.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE


def test_repair_bound_and_fixed_obligation_are_rejected_before_handler() -> None:
    calls = 0

    def handler(_request: adapters.StageRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _draft()

    too_many = _run(handler, _request(repair_attempt=2, repair={"failure": "x", "draft": "y"}))
    assert too_many.status is contracts.StageStatus.FAILED
    assert calls == 0

    multi = _run(handler, _request(obligation_ids=["obl-identity", "obl-other"]))
    assert multi.status is contracts.StageStatus.FAILED
    assert calls == 0
