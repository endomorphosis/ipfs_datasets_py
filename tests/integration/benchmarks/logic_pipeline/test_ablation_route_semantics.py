"""Focused evidence that the learned and SyMAI-ranked arms are real paths."""

from __future__ import annotations

import hashlib
import json

import pytest

from benchmarks.logic_pipeline import adapters, capabilities, contracts, runtime
from benchmarks.logic_pipeline.variants import get_variant_definition


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        contracts.canonical_json(value).encode("utf-8")
    ).hexdigest()


def _reviewed_chain() -> tuple[
    dict[str, object],
    runtime.CompiledObligation,
    runtime.ReviewedEntailmentTranslation,
]:
    value: dict[str, object] = {
        "text": (
            "Every red item is warm. Every warm item is safe. "
            "Object R is red. Therefore object R is safe."
        ),
        "obligation_id": "route-semantics-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "safe",
        },
    }
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
    return value, compiled, translation


def _compiler_artifact(
    compiled: runtime.CompiledObligation,
    translation: runtime.ReviewedEntailmentTranslation,
) -> adapters.StageArtifact:
    return adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {
            "compiled_obligation": compiled.to_dict(),
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
        },
        None,
        {"graph_invoked": True, "entrypoint": "test-compiler"},
        0,
    )


def _spacy_artifact(
    source_text: str,
    *,
    graph_invoked: bool | None = True,
) -> adapters.StageArtifact:
    identity: dict[str, object] = {
        "effective_model": "en_core_web_sm",
    }
    if graph_invoked is not None:
        identity["graph_invoked"] = graph_invoked
    return adapters.StageArtifact(
        contracts.StageName.SPACY,
        contracts.StageStatus.SUCCESS,
        {
            "schema": adapters.SPACY_EVIDENCE_SCHEMA,
            "document": {
                "normalized_text": source_text,
                "text_sha256": hashlib.sha256(
                    source_text.encode("utf-8")
                ).hexdigest(),
            },
            "execution": {"effective_model": "en_core_web_sm"},
            "sentences": [],
            "tokens": [],
            "dependencies": [],
            "entities": [],
            "semantic_roles": [],
            "modal_cues": [],
            "modal_ir": {
                "version": "1",
                "normalized_text": source_text,
                "formulas": [],
            },
        },
        None,
        identity,
        1,
    )


def _gated_symai_artifact() -> adapters.StageArtifact:
    return adapters.StageArtifact(
        contracts.StageName.SYMAI,
        contracts.StageStatus.SUCCESS,
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "policy-decision.v1"
            ),
            "stage": "symai",
            "invoked": False,
            "reason": "frontend_ambiguity_gate_closed",
            "invocation_index": 2,
        },
        None,
        {"graph_invoked": False, "invoked": False},
        2,
        invoked=False,
        policy_reason="frontend_ambiguity_gate_closed",
    )


def _live_symai_artifact() -> adapters.StageArtifact:
    candidate_ir = {
        "goal_predicate": "safe",
        "relevant_fact": "Object R is red",
    }
    return adapters.StageArtifact(
        contracts.StageName.SYMAI,
        contracts.StageStatus.SUCCESS,
        {
            "schema": adapters.SYMAI_EVIDENCE_SCHEMA,
            "candidate_ir": candidate_ir,
            "candidate_ir_sha256": _canonical_sha256(candidate_ir),
            "normalized_predicates": ["safe", "red"],
            "quantifiers": [],
            "entities": ["R"],
            "ambiguity_flags": [],
            "confidence": 0.9,
            "validation_errors": [],
            "assurance": {
                "semantic_hypothesis": True,
                "authoritative": False,
                "kernel_checked": False,
            },
        },
        None,
        {
            "graph_invoked": True,
            "provider": "test-provider",
            "model": "test-symai-model",
        },
        2,
    )


def _hammer_request(
    variant_id: str,
    *,
    symai: adapters.StageArtifact,
) -> tuple[
    adapters.StageRequest,
    runtime.ReviewedEntailmentTranslation,
]:
    value, compiled, translation = _reviewed_chain()
    definition = get_variant_definition(variant_id)
    return (
        adapters.StageRequest(
            run_id=f"route-{variant_id.lower()}",
            case_id="route-case",
            case_manifest_sha256="a" * 64,
            variant_id=variant_id,
            input_data=value,
            requested_identity=definition.requested_identity(
                contracts.StageName.HAMMER
            ),
            environment_sha256="b" * 64,
            upstream_artifacts=(
                _compiler_artifact(compiled, translation),
                _spacy_artifact(str(value["text"])),
                symai,
            ),
            invocation_index=3,
        ),
        translation,
    )


def _hammer_record() -> capabilities.CapabilityRecord:
    return capabilities.CapabilityRecord(
        capabilities.CapabilityKind.HAMMER,
        capabilities.CapabilityStatus.AVAILABLE,
        {
            "implementation": "test-hammer",
            "solver": "cvc5",
            "solver_path": "/test/cvc5",
        },
        ("route-semantics-test",),
    )


def _unsat_result(
    arguments: object,
    **_kwargs: object,
) -> capabilities.BoundedProcessResult:
    return capabilities.BoundedProcessResult(
        arguments=tuple(arguments),  # type: ignore[arg-type]
        returncode=0,
        stdout="unsat\n",
        stderr="",
        timed_out=False,
        process_group_reaped=True,
    )


def test_a10_runs_pinned_graph_selector_and_reorders_solver_premises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, translation = _hammer_request(
        "A10", symai=_gated_symai_artifact()
    )
    observed: list[bytes] = []

    def solve(arguments: object, **kwargs: object):
        observed.append(kwargs["input_bytes"])
        return _unsat_result(arguments, **kwargs)

    monkeypatch.setattr(runtime, "run_bounded_process_group", solve)
    output = runtime._hammer_live_handler(_hammer_record())(request)

    assert output.status is contracts.StageStatus.SUCCESS
    selection = output.data["premise_selection"]
    assert selection["ranking_contract"] == runtime.HAMMER_GRAPH_SELECTOR_CONTRACT
    assert selection["model_id"] == "graph-selector-default-v1"
    assert str(selection["model_digest"]).startswith("sha256:")
    assert selection["used_learned_selector"] is True
    assert selection["fallback_reason"] == "none"
    assert [item["source_index"] for item in selection["selected"]] == [2, 1, 0]
    ranked_problem = runtime._ranked_hammer_problem(
        translation, selection
    )
    assert ranked_problem != translation.smt2_problem
    assert observed == [ranked_problem.encode("utf-8")]
    assert output.effective_identity["premise_selection_sha256"] == (
        selection["receipt_sha256"]
    )


def test_a11_consumes_symai_ranking_and_kernel_recomputes_its_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    symai = _live_symai_artifact()
    request, translation = _hammer_request("A11", symai=symai)
    monkeypatch.setattr(
        runtime, "run_bounded_process_group", _unsat_result
    )
    output = runtime._hammer_live_handler(_hammer_record())(request)

    assert output.status is contracts.StageStatus.SUCCESS
    selection = output.data["premise_selection"]
    assert selection["ranking_contract"] == (
        runtime.HAMMER_SYMAI_RANKING_CONTRACT
    )
    assert selection["symai_invoked"] is True
    assert selection["symai_artifact_sha256"] == symai.digest
    assert [item["source_index"] for item in selection["selected"]] == [2, 0, 1]

    hammer = adapters.StageArtifact(
        contracts.StageName.HAMMER,
        contracts.StageStatus.SUCCESS,
        output.data,
        None,
        output.effective_identity,
        3,
    )
    kernel_request = adapters.StageRequest(
        run_id=request.run_id,
        case_id=request.case_id,
        case_manifest_sha256=request.case_manifest_sha256,
        variant_id="A11",
        input_data=request.input_data,
        requested_identity=get_variant_definition("A11").requested_identity(
            contracts.StageName.KERNEL
        ),
        environment_sha256=request.environment_sha256,
        upstream_artifacts=(*request.upstream_artifacts, hammer),
        invocation_index=4,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "kernel-state",
        expected_hammer_identity=_hammer_record().identity,
    )
    assert runner._validated_hammer_candidate(
        kernel_request, translation
    ) == (translation.hammer_proof_text, hammer.digest)

    tampered = json.loads(contracts.canonical_json(output.data))
    tampered["premise_selection"]["semantic_signal_sha256"] = "0" * 64
    tampered_hammer = adapters.StageArtifact(
        contracts.StageName.HAMMER,
        contracts.StageStatus.SUCCESS,
        tampered,
        None,
        output.effective_identity,
        3,
    )
    with pytest.raises(
        runtime.RuntimeBindingError,
        match="current translation",
    ):
        runner._validated_hammer_candidate(
            adapters.StageRequest(
                run_id=request.run_id,
                case_id=request.case_id,
                case_manifest_sha256=request.case_manifest_sha256,
                variant_id="A11",
                input_data=request.input_data,
                requested_identity=(
                    get_variant_definition("A11").requested_identity(
                        contracts.StageName.KERNEL
                    )
                ),
                environment_sha256=request.environment_sha256,
                upstream_artifacts=(
                    *request.upstream_artifacts,
                    tampered_hammer,
                ),
                invocation_index=4,
            ),
            translation,
        )


def test_measured_semantic_context_requires_truthful_graph_invocation() -> None:
    value, compiled, translation = _reviewed_chain()
    definition = get_variant_definition("A10")
    base = dict(
        run_id="semantic-truth",
        case_id="route-case",
        case_manifest_sha256="a" * 64,
        variant_id="A10",
        input_data=value,
        requested_identity=definition.requested_identity(
            contracts.StageName.HAMMER
        ),
        environment_sha256="b" * 64,
        invocation_index=3,
    )
    for graph_invoked, message in (
        (None, "omitted graph_invoked"),
        (False, "invocation receipt is inconsistent"),
    ):
        request = adapters.StageRequest(
            **base,
            upstream_artifacts=(
                _compiler_artifact(compiled, translation),
                _spacy_artifact(
                    str(value["text"]),
                    graph_invoked=graph_invoked,
                ),
                _gated_symai_artifact(),
            ),
        )
        with pytest.raises(contracts.ProtocolContractError, match=message):
            runtime._hammer_input_semantic_context(request)


def test_leanstral_provider_input_drops_evaluator_labels() -> None:
    observed: list[dict[str, object]] = []

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        assert isinstance(request.input_data, dict)
        observed.append(request.input_data)
        proof = "exact rfl"
        return {
            "schema_version": adapters.LEANSTRAL_DRAFT_SCHEMA,
            "artifact_id": "label-blind-draft",
            "artifact_kind": "llm_output",
            "stage": "model_draft",
            "draft_text": proof,
            "proof_text": proof,
            "request_id": "label-blind-request",
            "llm_provider": "leanstral_local",
            "model": "Leanstral",
            "obligation_ids": ["label-blind-obligation"],
            "resource_class": "model",
            "output_sha256": hashlib.sha256(
                proof.encode("utf-8")
            ).hexdigest(),
            "assurance": "unverified",
            "verified": False,
            "authoritative": False,
            "kernel_checked": False,
        }

    record = adapters.LeanstralAdapter(handler).run(
        adapters.StageRequest(
            run_id="label-blind",
            case_id="label-blind-case",
            case_manifest_sha256="a" * 64,
            variant_id="A3",
            input_data={
                "text": "Prove the fixed obligation.",
                "prompt": "Prove the fixed obligation.",
                "obligation_id": "label-blind-obligation",
                "expected_class": "proved",
                "expected_ir": {"secret": "label"},
                "difficulty": "easy",
                "negative_controls": ["leak"],
            },
        )
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(observed) == 1
    assert not {
        "expected_class",
        "expected_ir",
        "difficulty",
        "negative_controls",
    }.intersection(observed[0])
