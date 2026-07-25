"""Integration evidence for the exact frozen-arm runtime dataflow."""

from __future__ import annotations

from dataclasses import replace
import json
import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest

from benchmarks.logic_pipeline import (
    ablation,
    adapters,
    cache_measurement,
    contracts,
    matrix_reassessment,
    metrics,
    runtime,
    variants,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        contracts.canonical_json(value).encode("utf-8")
    ).hexdigest()


def _case(
    *, ambiguous: bool = True, proof_obligation: bool = True
) -> ablation.AblationCase:
    proof_fields: dict[str, object] = (
        {
            "obligation_id": "case-1-obligation",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
        if proof_obligation
        else {"proof_obligation": None}
    )
    return ablation.AblationCase.create(
        "case-1",
        {
            "text": (
                "Every reviewer is trained. Alice is a reviewer. "
                "Therefore Alice is trained."
            ),
            **proof_fields,
            "ambiguity_detected": ambiguous,
        },
        split=contracts.Split.PILOT,
    )


def _plan(
    variant_id: str,
    *,
    ambiguous: bool = True,
) -> ablation.AblationPlan:
    return ablation.build_ablation_plan(
        f"dataflow-{variant_id.lower()}",
        (_case(ambiguous=ambiguous),),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=7,
        variant_ids=(variant_id,),
        cache_modes=(contracts.CacheMode.COLD,),
        environment_sha256="b" * 64,
    )


def _fully_rehashed_suppressed_result(
    plan: ablation.AblationPlan,
    *,
    invocation_order: tuple[contracts.StageName, ...] | None = None,
) -> contracts.CaseResultRecord:
    """Build a self-consistent forged graph without reusing stale digests."""

    job = plan.jobs[0]
    definition = variants.get_variant_definition(job.variant_id)
    order = invocation_order or ablation._frozen_invocation_order(definition)
    reasons = {
        contracts.StageName.COMPILER: "frontend_scheduled",
        contracts.StageName.SPACY: "frontend_scheduled",
        contracts.StageName.SYMAI: "frontend_ambiguity_gate_open",
        contracts.StageName.HAMMER: "proof_failure_fallback",
        contracts.StageName.LEANSTRAL: "proof_scheduled",
        contracts.StageName.KERNEL: "independent_native_kernel",
    }
    invocations: dict[
        contracts.StageName, adapters.StageInvocation
    ] = {}
    artifacts: list[adapters.StageArtifact] = []
    for invocation_index, stage in enumerate(order):
        request = adapters.StageRequest(
            run_id=plan.run_id,
            case_id=job.case.case_id,
            case_manifest_sha256=plan.case_manifest_sha256,
            variant_id=job.variant_id,
            split=plan.split,
            cache_mode=job.cache_mode,
            input_data=ablation._thaw(job.case.input_data),
            requested_identity=definition.requested_identity(stage),
            environment_sha256=plan.environment_sha256,
            source=("adversarial_test", plan.digest, job.job_id),
            upstream_artifacts=tuple(artifacts),
            invocation_index=invocation_index,
        )
        invocation = ablation._synthetic_invocation(
            stage,
            request,
            reason=reasons[stage],
        )
        invocations[stage] = invocation
        artifacts.append(
            ablation._artifact(
                stage,
                invocation,
                invocation_index=invocation_index,
                invoked=False,
                reason=reasons[stage],
            )
        )

    records: list[contracts.StageRecord] = []
    canonical_upstream: tuple[str, ...] = ()
    for stage in definition.stages:
        artifact = next(item for item in artifacts if item.stage is stage)
        request = adapters.StageRequest(
            run_id=plan.run_id,
            case_id=job.case.case_id,
            case_manifest_sha256=plan.case_manifest_sha256,
            variant_id=job.variant_id,
            split=plan.split,
            cache_mode=job.cache_mode,
            input_data=ablation._thaw(job.case.input_data),
            requested_identity=definition.requested_identity(stage),
            environment_sha256=plan.environment_sha256,
            source=("adversarial_test", plan.digest, job.job_id),
            upstream_stage_digests=canonical_upstream,
            upstream_artifacts=tuple(artifacts),
            invocation_index=artifact.invocation_index,
        )
        record = adapters.StageAdapter(stage).record(
            request,
            invocations[stage],
        )
        records.append(record)
        canonical_upstream = (*canonical_upstream, record.digest)
    return contracts.CaseResultRecord.from_stages(tuple(records))


class _GraphHandlers:
    def __init__(
        self,
        *,
        hammer_success: bool = False,
        compiler_data: dict[str, object] | None = None,
        compiler_entrypoint: bool = False,
        kernel_accepts: bool = True,
    ) -> None:
        self.calls: list[contracts.StageName] = []
        self.requests: dict[contracts.StageName, adapters.StageRequest] = {}
        self.hammer_success = hammer_success
        self.compiler_data = compiler_data
        self.compiler_entrypoint = compiler_entrypoint
        self.kernel_accepts = kernel_accepts

    def mapping(self) -> MappingProxyType:
        return MappingProxyType(
            {
                stage: adapters.StageAdapter(
                    stage, handler=self._handler(stage)
                )
                for stage in contracts.StageName
            }
        )

    def _handler(self, stage: contracts.StageName):
        def invoke(request: adapters.StageRequest) -> adapters.StageOutput:
            self.calls.append(stage)
            self.requests[stage] = request
            if stage is contracts.StageName.COMPILER:
                return adapters.StageOutput(
                    data={
                        "stage": stage.value,
                        "ambiguity_detected": request.input_data[
                            "ambiguity_detected"
                        ],
                        **(self.compiler_data or {}),
                    },
                    effective_identity=(
                        {
                            "entrypoint": (
                                "ipfs_datasets_py.logic.modal.codec."
                                "DeterministicModalLogicCodec.encode"
                            )
                        }
                        if self.compiler_entrypoint
                        else {}
                    ),
                )
            if stage is contracts.StageName.HAMMER:
                return adapters.StageOutput(
                    data={
                        "stage": stage.value,
                        "proof_success": self.hammer_success,
                        "proof_text": "exact hammer_candidate",
                    }
                )
            if stage is contracts.StageName.LEANSTRAL:
                return adapters.StageOutput(
                    data={
                        "stage": stage.value,
                        "proof_success": True,
                        "proof_text": "exact leanstral_candidate",
                    }
                )
            if stage is contracts.StageName.KERNEL:
                receipt: dict[str, object] = {
                    "schema": contracts.NATIVE_KERNEL_RECEIPT_SCHEMA,
                    "protocol_sha256": request.protocol_sha256,
                    "run_id": request.run_id,
                    "case_id": request.case_id,
                    "case_manifest_sha256": (
                        request.case_manifest_sha256
                    ),
                    "variant_id": request.variant_id,
                    "split": request.split.value,
                    "cache_mode": request.cache_mode.value,
                    "input_sha256": request.input_sha256,
                    "environment_sha256": request.environment_sha256,
                    "independent": True,
                    "accepted": self.kernel_accepts,
                    "active_process_count": 0,
                }
                if self.kernel_accepts:
                    candidate_sha256 = request.upstream_artifacts[0].digest
                    attempt_body = {
                        "attempt_index": 0,
                        "candidate_source": (
                            contracts.StageName.COMPILER.value
                        ),
                        "candidate_artifact_sha256": candidate_sha256,
                        "source_sha256": _sha("source"),
                        "command_sha256": _sha("command"),
                        "stdout_sha256": _sha("accepted"),
                        "stderr_sha256": _sha(""),
                        "returncode": 0,
                        "timed_out": False,
                        "cancelled": False,
                        "resource_exhausted": False,
                        "termination_reason": "completed",
                        "process_group_reaped": True,
                        "active_process_count": 0,
                        "accepted": True,
                    }
                    attempt = {
                        **attempt_body,
                        "attempt_sha256": _sha(attempt_body),
                    }
                    receipt.update(
                        {
                            "compiled_obligation_sha256": _sha("compiled"),
                            "obligation_sha256": _sha("obligation"),
                            "candidate_source": attempt[
                                "candidate_source"
                            ],
                            "candidate_artifact_sha256": candidate_sha256,
                            "source_sha256": attempt["source_sha256"],
                            "semantic_context_sha256": _sha(
                                "semantic-context"
                            ),
                            "semantic_artifact_sha256s": [
                                artifact.digest
                                for artifact in request.upstream_artifacts
                            ],
                            "command_sha256": attempt["command_sha256"],
                            "stdout_sha256": attempt["stdout_sha256"],
                            "stderr_sha256": attempt["stderr_sha256"],
                            "returncode": attempt["returncode"],
                            "timed_out": attempt["timed_out"],
                            "cancelled": attempt["cancelled"],
                            "resource_exhausted": attempt[
                                "resource_exhausted"
                            ],
                            "termination_reason": attempt[
                                "termination_reason"
                            ],
                            "process_group_reaped": attempt[
                                "process_group_reaped"
                            ],
                            "candidate_attempts": [attempt],
                            "candidate_attempts_sha256": _sha([attempt]),
                            "selected_attempt": {
                                key: attempt[key]
                                for key in (
                                    "attempt_index",
                                    "candidate_source",
                                    "candidate_artifact_sha256",
                                    "attempt_sha256",
                                    "accepted",
                                )
                            },
                        }
                    )
                else:
                    receipt["reason"] = "no_proof_candidate"
                receipt_sha256 = _sha(receipt)
                return adapters.StageOutput(
                    data={
                        **receipt,
                        "receipt_sha256": receipt_sha256,
                    },
                    kernel_accepted=self.kernel_accepts,
                    kernel_receipt_sha256=(
                        receipt_sha256 if self.kernel_accepts else None
                    ),
                )
            return adapters.StageOutput(data={"stage": stage.value})

        return invoke


def _unsupported_runtime_compiler_data() -> dict[str, object]:
    unsupported_input = {
        **dict(_case().input_data),
        "text": "Every reviewer is trained. Alice is a reviewer.",
    }
    compiled = runtime.compile_reviewed_obligation(unsupported_input)
    assert compiled is not None
    assert "translation:unsupported" in compiled.source_template
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
        ),
        "compiled_obligation": compiled.to_dict(),
        "compiled_obligation_sha256": compiled.digest,
        "entailment_translation": None,
        "entailment_translation_sha256": None,
        "native_proof_candidate": None,
    }


def _supported_runtime_compiler_data(
    input_data: object | None = None,
) -> dict[str, object]:
    value = _case().input_data if input_data is None else input_data
    assert isinstance(value, MappingProxyType | dict)
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
    assert translation.native_proof_text is not None
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
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
        ),
        "compiled_obligation": compiled.to_dict(),
        "compiled_obligation_sha256": compiled.digest,
        "entailment_translation": translation.to_dict(),
        "entailment_translation_sha256": translation.digest,
        "native_proof_candidate": candidate,
    }


@pytest.mark.parametrize(
    ("variant_id", "expected_proof_calls"),
    [
        ("A0", ()),
        ("A1", ()),
        ("A2", (contracts.StageName.HAMMER,)),
        ("A3", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A4", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A5", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A6", (contracts.StageName.LEANSTRAL,)),
        ("A7", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A8", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A9", (contracts.StageName.LEANSTRAL,)),
        ("A10", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        ("A11", (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL)),
        (
            "A12",
            (contracts.StageName.LEANSTRAL, contracts.StageName.HAMMER),
        ),
        ("S1", ()),
    ],
)
def test_every_arm_executes_its_registered_graph_and_proof_order(
    tmp_path: Path,
    variant_id: str,
    expected_proof_calls: tuple[contracts.StageName, ...],
) -> None:
    graph = _GraphHandlers()
    plan = _plan(variant_id)
    run = ablation.execute_ablation(
        plan,
        graph.mapping(),
        output_root=tmp_path / variant_id,
        resume=False,
    )
    result = run.results[0]
    proof_calls = tuple(
        stage
        for stage in graph.calls
        if stage in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    )

    assert proof_calls == expected_proof_calls
    assert tuple(stage.stage for stage in result.stages) == (
        variants.get_variant_definition(variant_id).stages
    )
    assert result.validate_provenance() is None
    assert run.contracts == plan.run_contracts
    assert len(
        {
            (contract.requested_variant_id, contract.cache_mode)
            for contract in run.contracts
        }
    ) == len(run.contracts)
    if contracts.StageName.KERNEL in graph.requests:
        kernel = graph.requests[contracts.StageName.KERNEL]
        assert kernel.upstream_artifacts
        assert kernel.input_sha256 == plan.jobs[0].input_sha256
    if variant_id == "S1":
        assert result.status is not contracts.OutcomeStatus.VERIFIED
        assert result.kernel_accepted is False
        assert result.terminal_kernel_accepted is True
        kernel_record = result.stages[-1]
        assert kernel_record.stage is contracts.StageName.KERNEL
        assert kernel_record.kernel_accepted is False
        assert kernel_record.data["accepted"] is False
        assert (
            kernel_record.data["reason"]
            == "diagnostic_only_authority_withheld"
        )
        assert kernel_record.data["diagnostic_only"] is True
        assert kernel_record.data["authority_withheld"] is True
        assert kernel_record.data["diagnostic_kernel_accepted"] is True
        assert kernel_record.data["diagnostic_receipt"]["accepted"] is True
        assert (
            kernel_record.data["diagnostic_receipt_sha256"]
            == kernel_record.data["diagnostic_receipt"]["receipt_sha256"]
        )


def test_s1_rejects_rehashed_nested_diagnostic_from_another_case(
    tmp_path: Path,
) -> None:
    result = ablation.execute_ablation(
        _plan("S1"),
        _GraphHandlers().mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]
    assert result.terminal_kernel_accepted is True

    kernel_value = json.loads(
        contracts.canonical_json(result.stages[-1].to_dict())
    )
    data = kernel_value["data"]
    nested = data["diagnostic_receipt"]
    nested["case_id"] = "copied-diagnostic-case"
    nested["receipt_sha256"] = _sha(
        {
            key: value
            for key, value in nested.items()
            if key != "receipt_sha256"
        }
    )
    data["diagnostic_receipt_sha256"] = nested["receipt_sha256"]
    data["receipt_sha256"] = _sha(
        {
            key: value
            for key, value in data.items()
            if key not in {"receipt_sha256", "routing_policy"}
        }
    )
    kernel_value["output_sha256"] = _sha(data)
    copied = contracts.StageRecord.from_dict(kernel_value)

    with pytest.raises(
        contracts.ProtocolContractError,
        match="coordinate or source binding",
    ):
        contracts.CaseResultRecord.from_stages(
            (*result.stages[:-1], copied)
        )


def test_unsupported_raw_kernel_acceptance_stops_before_the_next_job(
    tmp_path: Path,
) -> None:
    cases = tuple(
        ablation.AblationCase.create(
            f"unsupported-{index}",
            {
                "text": "An unsupported control must not be verified.",
                "ambiguity_detected": False,
                "expected_class": "unsupported",
                "proof_obligation": None,
            },
            split=contracts.Split.PILOT,
        )
        for index in range(2)
    )
    plan = ablation.build_ablation_plan(
        "invalid-control-stop",
        cases,
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=19,
        variant_ids=("A1",),
        cache_modes=(contracts.CacheMode.COLD,),
        environment_sha256="b" * 64,
    )
    graph = _GraphHandlers(kernel_accepts=True)

    run = ablation.execute_ablation(
        plan,
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    )

    assert run.complete is False
    assert (
        run.stop_failure_code
        is contracts.FailureCode.INVALID_CONTROL_VERIFIED
    )
    assert len(run.results) == 1
    assert run.results[0].status is contracts.OutcomeStatus.VERIFIED
    assert run.results[0].failure_code is None
    assert run.results[0].terminal_kernel_accepted is True
    assert graph.calls == [
        contracts.StageName.COMPILER,
        contracts.StageName.SPACY,
        contracts.StageName.KERNEL,
    ]
    assert run.result_paths[0].is_file()
    assert not run.result_paths[1].exists()


def test_ambiguity_gate_is_zero_call_but_retains_typed_stage_record(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers()
    run = ablation.execute_ablation(
        _plan("A4", ambiguous=False),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    )
    result = run.results[0]
    symai = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.SYMAI
    )

    assert contracts.StageName.SYMAI not in graph.calls
    assert symai.status is contracts.StageStatus.SUCCESS
    assert symai.data["invoked"] is False
    assert symai.data["reason"] == "frontend_ambiguity_gate_closed"
    assert symai.telemetry.model_calls == 0
    assert symai.provenance.effective_identity["graph_invoked"] is False


def test_hammer_success_suppresses_bounded_fallback_and_flows_artifacts(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers(hammer_success=True)
    run = ablation.execute_ablation(
        _plan("A4"),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    )
    result = run.results[0]
    leanstral = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.LEANSTRAL
    )

    assert contracts.StageName.LEANSTRAL not in graph.calls
    assert leanstral.data["invoked"] is False
    assert leanstral.data["reason"] == "proof_fallback_suppressed"
    assert graph.requests[contracts.StageName.KERNEL].artifact(
        contracts.StageName.HAMMER
    ) is not None
    assert result.status is contracts.OutcomeStatus.VERIFIED


def test_lean_first_invocation_is_preserved_with_canonical_durable_records(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers(hammer_success=False)
    run = ablation.execute_ablation(
        _plan("A12"),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    )
    result = run.results[0]
    proof_calls = [
        stage
        for stage in graph.calls
        if stage in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    ]

    assert proof_calls == [
        contracts.StageName.LEANSTRAL,
        contracts.StageName.HAMMER,
    ]
    assert [
        stage.stage
        for stage in result.stages
        if stage.stage
        in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    ] == [contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL]
    hammer_record = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.HAMMER
    )
    assert hammer_record.provenance.effective_identity[
        "graph_invocation_index"
    ] < next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.KERNEL
    ).provenance.effective_identity["graph_invocation_index"]
    assert result.validate_provenance() is None


def test_failed_lean_first_attempt_executes_registered_hammer_fallback(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers(hammer_success=True)
    route = dict(graph.mapping())

    def unavailable_leanstral(
        request: adapters.StageRequest,
    ) -> adapters.StageOutput:
        graph.calls.append(contracts.StageName.LEANSTRAL)
        graph.requests[contracts.StageName.LEANSTRAL] = request
        return adapters.StageOutput(
            status=contracts.StageStatus.UNAVAILABLE,
            failure_code=contracts.FailureCode.CAPABILITY_UNAVAILABLE,
            failure_detail="test Leanstral backend unavailable",
        )

    route[contracts.StageName.LEANSTRAL] = adapters.StageAdapter(
        contracts.StageName.LEANSTRAL,
        unavailable_leanstral,
    )
    run = ablation.execute_ablation(
        _plan("A6"),
        route,
        output_root=tmp_path,
        resume=False,
    )

    assert [
        stage
        for stage in graph.calls
        if stage in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    ] == [contracts.StageName.LEANSTRAL, contracts.StageName.HAMMER]
    assert contracts.StageName.KERNEL in graph.calls
    assert run.results[0].stages[-1].kernel_accepted
    assert run.results[0].status is contracts.OutcomeStatus.UNAVAILABLE


def test_explicit_unsupported_compiler_translation_suppresses_proof_calls_but_not_kernel(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers(
        compiler_data=_unsupported_runtime_compiler_data(),
        kernel_accepts=False,
    )
    result = ablation.execute_ablation(
        _plan("A12"),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]

    assert contracts.StageName.HAMMER not in graph.calls
    assert contracts.StageName.LEANSTRAL not in graph.calls
    assert contracts.StageName.KERNEL in graph.calls
    proof_records = [
        stage
        for stage in result.stages
        if stage.stage
        in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    ]
    assert {stage.stage for stage in proof_records} == {
        contracts.StageName.HAMMER,
        contracts.StageName.LEANSTRAL,
    }
    for stage in proof_records:
        assert stage.status is contracts.StageStatus.SUCCESS
        assert stage.data["invoked"] is False
        assert stage.data["reason"] == "compiler_translation_unsupported"
        assert stage.provenance.effective_identity["graph_invoked"] is False
        assert stage.telemetry.model_calls == 0
    kernel = result.stages[-1]
    assert kernel.stage is contracts.StageName.KERNEL
    assert kernel.provenance.effective_identity["graph_invoked"] is True
    assert kernel.data["reason"] == "no_proof_candidate"
    assert result.status is contracts.OutcomeStatus.NOT_VERIFIED
    assert result.validate_provenance() is None


def test_incomplete_compiler_contract_fails_open_for_injected_handlers(
    tmp_path: Path,
) -> None:
    partial = _unsupported_runtime_compiler_data()
    partial.pop("native_proof_candidate")
    graph = _GraphHandlers(compiler_data=partial)
    result = ablation.execute_ablation(
        _plan("A9"),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]

    assert contracts.StageName.LEANSTRAL in graph.calls
    leanstral = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.LEANSTRAL
    )
    assert leanstral.provenance.effective_identity["graph_invoked"] is True
    assert result.status is contracts.OutcomeStatus.VERIFIED


def test_a9_suppresses_index_zero_leanstral_fallback_for_source_bound_native_candidate(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers(
        compiler_data=_supported_runtime_compiler_data(),
        compiler_entrypoint=True,
    )
    result = ablation.execute_ablation(
        _plan("A9"),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]

    assert contracts.StageName.LEANSTRAL not in graph.calls
    assert contracts.StageName.KERNEL in graph.calls
    leanstral = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.LEANSTRAL
    )
    assert leanstral.status is contracts.StageStatus.SUCCESS
    assert leanstral.data["invoked"] is False
    assert leanstral.data["reason"] == "proof_fallback_suppressed"
    assert leanstral.provenance.effective_identity["graph_invoked"] is False
    assert leanstral.telemetry.model_calls == 0
    assert result.status is contracts.OutcomeStatus.VERIFIED
    assert result.validate_provenance() is None


def test_warm_symai_ablation_primes_then_measures_under_one_graph_stage(
    tmp_path: Path,
) -> None:
    class Engine:
        calls = 0

        def forward(self, _argument: object):
            self.calls += 1
            return (
                [
                    json.dumps(
                        {
                            "candidate_ir": {
                                "kind": "fol",
                                "propositions": ["Trained"],
                            },
                            "normalized_predicates": [
                                "Reviewer",
                                "Trained",
                            ],
                            "quantifiers": ["forall"],
                            "entities": ["Alice"],
                            "ambiguity_flags": [],
                            "confidence": 0.95,
                            "validation_errors": [],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ],
                {
                    "backend": "llm_router",
                    "effective_provider_name": "ipfs_accelerate_py",
                    "effective_model_name": "Leanstral-119B",
                },
            )

    engine = Engine()
    graph = _GraphHandlers()
    route = dict(graph.mapping())
    route[contracts.StageName.COMPILER] = adapters.CompilerAdapter(
        runtime._current_compiler_handler
    )
    route[contracts.StageName.SPACY] = adapters.SpacyAdapter(
        config=adapters.SpacyAdapterConfig(
            mode=adapters.SpacyAdapterMode.REGEX_LEGAL
        )
    )
    route[contracts.StageName.SYMAI] = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            provider="ipfs_accelerate_py",
            model="Leanstral-119B",
            max_retries=0,
            cache_enabled=True,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {},
        cache={},
    )
    plan = ablation.build_ablation_plan(
        "dataflow-warm-symai",
        (_case(),),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=7,
        variant_ids=("A5",),
        cache_modes=(
            contracts.CacheMode.COLD,
            contracts.CacheMode.WARM,
        ),
        environment_sha256="b" * 64,
    )

    run = ablation.execute_ablation(
        plan,
        route,
        output_root=tmp_path,
        resume=False,
    )
    result = next(
        item
        for item in run.results
        if item.cache_mode is contracts.CacheMode.WARM
    )
    symai = next(
        stage
        for stage in result.stages
        if stage.stage is contracts.StageName.SYMAI
    )
    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        symai
    )

    assert engine.calls == 2
    assert symai.provenance.effective_identity["graph_invoked"] is True
    assert symai.telemetry.model_calls == 0
    assert symai.telemetry.cache_hits == 1
    assert symai.telemetry.cache_misses == 0
    assert receipt.setup_telemetry.model_calls == 1
    assert receipt.setup_telemetry.cache_hits == 0
    assert receipt.setup_telemetry.cache_misses == 1
    assert result.status is contracts.OutcomeStatus.VERIFIED
    ledger_path = matrix_reassessment._ledger_path(tmp_path)
    ledger = matrix_reassessment._build_ledger(run)
    matrix_reassessment._write_once(ledger_path, ledger)
    summary = matrix_reassessment._split_summary(
        run=run,
        split_root=tmp_path,
        index_path=tmp_path / "matrix-index.json",
        ledger_path=ledger_path,
        ledger=ledger,
    )
    cache_summary = summary["symai_cache_measurement"]
    assert cache_summary["prime_receipt_count"] == 1
    assert cache_summary["measured_invocation_count"] == 1
    assert cache_summary["backend_invocation_count"] == 2
    assert cache_summary["measured_hit_count"] == 1
    assert cache_summary["prime_failure_count"] == 0
    assert cache_summary["cache_setup_model_calls"] == 1
    assert cache_summary["measured_model_calls"] == 0
    assert cache_summary["inclusive_model_calls"] == 1
    assert cache_summary["leanstral_cache_semantics"] == "not_applicable"
    aggregate = metrics.aggregate_case_results([result])
    measured_model_calls = sum(
        stage.telemetry.model_calls for stage in result.stages
    )
    assert (
        aggregate.telemetry_totals["model_calls"]
        == measured_model_calls + 1
    )
    measured_model_stages = sum(
        stage.telemetry.resource_lane is contracts.ResourceLane.MODEL
        for stage in result.stages
    )
    assert (
        aggregate.resource_lane_measurements["model"]["stage_count"]
        == measured_model_stages + 1
    )
    symai_cost = metrics.EfficiencyComponentCost(
        component_id="symai",
        model_calls=1,
        solver_processes=0,
        solver_processes_missing_reason=None,
        accelerator_minutes=0.0,
        accelerator_minutes_missing_reason=None,
        retries=0,
        component_calls=2,
        useful_component_calls=0,
        failed_attempts=0,
    )
    resource_receipt = metrics.EfficiencyResourceReceipt(
        case_result_sha256=result.digest,
        environment_sha256="b" * 64,
        measurement_sha256="d" * 64,
        component_costs=(symai_cost,),
    )
    assert metrics.EfficiencyObservation(
        case_result=result,
        resource_receipt=resource_receipt,
        invalid_control=False,
    ).resource_receipt == resource_receipt
    forged_cost_fields = (
        {"component_calls": 1},
        {"component_calls": 3},
        {"useful_component_calls": 1},
        {"failed_attempts": 1},
    )
    for index, forged_fields in enumerate(forged_cost_fields, start=1):
        forged_receipt = metrics.EfficiencyResourceReceipt(
            case_result_sha256=result.digest,
            environment_sha256="b" * 64,
            measurement_sha256=f"{index:x}" * 64,
            component_costs=(
                metrics.EfficiencyComponentCost(
                    **{
                        **symai_cost.to_dict(),
                        **forged_fields,
                    }
                ),
            ),
        )
        with pytest.raises(
            metrics.MetricsContractError,
            match="component-call attribution",
        ):
            metrics.EfficiencyObservation(
                case_result=result,
                resource_receipt=forged_receipt,
                invalid_control=False,
            )


def test_current_warm_nonlegacy_symai_cannot_omit_prime_receipt(
    tmp_path: Path,
) -> None:
    plan = ablation.build_ablation_plan(
        "dataflow-warm-symai-missing-prime",
        (_case(proof_obligation=False),),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=7,
        variant_ids=("A5",),
        cache_modes=(contracts.CacheMode.WARM,),
        environment_sha256="b" * 64,
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="omitted its cache-prime receipt",
    ):
        ablation.execute_ablation(
            plan,
            _GraphHandlers().mapping(),
            output_root=tmp_path,
            resume=False,
        )


def test_current_v2_envelope_rejects_masked_terminal_kernel_acceptance(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers()
    route = dict(graph.mapping())

    def failed_leanstral(
        request: adapters.StageRequest,
    ) -> adapters.StageOutput:
        graph.calls.append(contracts.StageName.LEANSTRAL)
        graph.requests[contracts.StageName.LEANSTRAL] = request
        return adapters.StageOutput(
            status=contracts.StageStatus.FAILED,
            failure_code=(
                contracts.FailureCode
                .LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
            ),
            failure_detail="bounded test proof-attempt failure",
        )

    route[contracts.StageName.LEANSTRAL] = adapters.LeanstralAdapter(
        failed_leanstral
    )
    plan = _plan("A6")
    run = ablation.execute_ablation(
        plan,
        route,
        output_root=tmp_path,
        resume=False,
    )
    assert run.results[0].status is contracts.OutcomeStatus.VERIFIED

    result_path = run.result_paths[0]
    envelope = json.loads(result_path.read_text(encoding="utf-8"))
    assert envelope["schema"] == ablation.ABLATION_RESULT_SCHEMA
    case_result = envelope["case_result"]
    case_result.update(
        {
            "status": contracts.OutcomeStatus.REJECTED.value,
            "verification_authority": (
                contracts.VerificationAuthority.NONE.value
            ),
            "kernel_accepted": False,
            "kernel_receipt_sha256": None,
            "failure_code": (
                contracts.FailureCode
                .LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT.value
            ),
            "failure_detail": "legacy masked projection",
        }
    )
    masked = contracts.CaseResultRecord.from_dict(case_result)
    envelope["case_result_sha256"] = masked.digest
    result_path.write_text(
        contracts.canonical_json(envelope) + "\n", encoding="utf-8"
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="masks its canonical terminal outcome",
    ):
        ablation.validate_ablation_evidence(
            plan, output_root=tmp_path
        )


def test_current_v2_envelope_rejects_normalized_noncanonical_wire_record(
    tmp_path: Path,
) -> None:
    plan = _plan("A1")
    run = ablation.execute_ablation(
        plan,
        _GraphHandlers().mapping(),
        output_root=tmp_path,
        resume=False,
    )
    result_path = run.result_paths[0]
    envelope = json.loads(result_path.read_text(encoding="utf-8"))
    envelope["case_result"]["receipt"] = None
    normalized = contracts.CaseResultRecord.from_dict(
        envelope["case_result"]
    )
    envelope["case_result_sha256"] = normalized.digest
    result_path.write_text(
        contracts.canonical_json(envelope) + "\n", encoding="utf-8"
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="noncanonical wire record",
    ):
        ablation.validate_ablation_evidence(
            plan, output_root=tmp_path
        )


def test_current_v2_graph_rejects_a_missing_registered_stage(
    tmp_path: Path,
) -> None:
    plan = _plan("A5")
    run = ablation.execute_ablation(
        plan,
        _GraphHandlers(kernel_accepts=False).mapping(),
        output_root=tmp_path,
        resume=False,
    )
    forged = contracts.CaseResultRecord.from_stages(
        tuple(
            stage
            for stage in run.results[0].stages
            if stage.stage is not contracts.StageName.SYMAI
        )
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="route differs from the frozen variant definition",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_current_v2_graph_rejects_a_substituted_registered_stage(
    tmp_path: Path,
) -> None:
    plan = _plan("A9")
    run = ablation.execute_ablation(
        plan,
        _GraphHandlers(kernel_accepts=False).mapping(),
        output_root=tmp_path,
        resume=False,
    )
    symai = next(
        stage
        for stage in run.results[0].stages
        if stage.stage is contracts.StageName.SYMAI
    )
    substituted = replace(
        symai,
        stage=contracts.StageName.HAMMER,
        telemetry=replace(
            symai.telemetry,
            resource_lane=contracts.ResourceLane.SOLVER,
        ),
    )
    forged = contracts.CaseResultRecord.from_stages(
        tuple(
            substituted if stage is symai else stage
            for stage in run.results[0].stages
        )
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="route differs from the frozen variant definition",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_current_v2_graph_rejects_reordered_invocation_indices(
    tmp_path: Path,
) -> None:
    plan = _plan("A6")
    run = ablation.execute_ablation(
        plan,
        _GraphHandlers(kernel_accepts=False).mapping(),
        output_root=tmp_path,
        resume=False,
    )
    compiler = next(
        stage
        for stage in run.results[0].stages
        if stage.stage is contracts.StageName.COMPILER
    )
    spacy = next(
        stage
        for stage in run.results[0].stages
        if stage.stage is contracts.StageName.SPACY
    )
    compiler_index = compiler.provenance.effective_identity[
        "graph_invocation_index"
    ]
    spacy_index = spacy.provenance.effective_identity[
        "graph_invocation_index"
    ]
    replacements = {
        contracts.StageName.COMPILER: replace(
            compiler,
            provenance=replace(
                compiler.provenance,
                effective_identity={
                    **dict(compiler.provenance.effective_identity),
                    "graph_invocation_index": spacy_index,
                },
            ),
        ),
        contracts.StageName.SPACY: replace(
            spacy,
            provenance=replace(
                spacy.provenance,
                effective_identity={
                    **dict(spacy.provenance.effective_identity),
                    "graph_invocation_index": compiler_index,
                },
            ),
        ),
    }
    forged = contracts.CaseResultRecord.from_stages(
        tuple(
            replacements.get(stage.stage, stage)
            for stage in run.results[0].stages
        )
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="differs from the frozen invocation order",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_current_v2_graph_rejects_fully_rehashed_invocation_permutation() -> None:
    plan = _plan("A6")
    frozen = ablation._frozen_invocation_order(
        variants.get_variant_definition("A6")
    )
    permutation = (frozen[1], frozen[0], *frozen[2:])
    forged = _fully_rehashed_suppressed_result(
        plan,
        invocation_order=permutation,
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="differs from the frozen invocation order",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_current_v2_graph_rejects_fully_rehashed_all_suppressed_route() -> None:
    plan = _plan("A6")
    forged = _fully_rehashed_suppressed_result(plan)
    assert all(
        stage.provenance.effective_identity["graph_invoked"] is False
        for stage in forged.stages
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="invocation decision differs from the frozen policy at compiler",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_current_v2_graph_rejects_invoked_stage_as_forged_suppression(
    tmp_path: Path,
) -> None:
    plan = _plan("A5")
    run = ablation.execute_ablation(
        plan,
        _GraphHandlers(kernel_accepts=False).mapping(),
        output_root=tmp_path,
        resume=False,
    )
    symai = next(
        stage
        for stage in run.results[0].stages
        if stage.stage is contracts.StageName.SYMAI
    )
    forged_stage = replace(
        symai,
        provenance=replace(
            symai.provenance,
            effective_identity={
                **dict(symai.provenance.effective_identity),
                "graph_invoked": False,
                "policy_reason": "forged_suppression",
            },
        ),
    )
    forged = contracts.CaseResultRecord.from_stages(
        tuple(
            forged_stage if stage is symai else stage
            for stage in run.results[0].stages
        )
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="lacks its exact graph decision receipt",
    ):
        ablation.validate_current_result_graph(
            forged,
            plan=plan,
            job=plan.jobs[0],
        )


def test_a9_native_candidate_gate_fails_open_for_legacy_malformed_and_wrong_source(
    tmp_path: Path,
) -> None:
    legacy = _supported_runtime_compiler_data()
    legacy.pop("schema")

    malformed = _supported_runtime_compiler_data()
    malformed_candidate = dict(malformed["native_proof_candidate"])
    malformed_candidate["unexpected"] = True
    malformed["native_proof_candidate"] = malformed_candidate

    invalid_certificate = _supported_runtime_compiler_data()
    invalid_candidate = dict(
        invalid_certificate["native_proof_candidate"]
    )
    invalid_candidate["certificate"] = "by sorry"
    invalid_certificate["native_proof_candidate"] = invalid_candidate

    different_input = dict(_case().input_data)
    different_input["text"] = (
        "Every reviewer is trained. Bob is a reviewer. "
        "Therefore Bob is trained."
    )
    wrong_source = _supported_runtime_compiler_data(different_input)

    for index, (compiler_data, compiler_entrypoint) in enumerate(
        (
            (_supported_runtime_compiler_data(), False),
            (legacy, True),
            (malformed, True),
            (wrong_source, True),
            (invalid_certificate, True),
        )
    ):
        graph = _GraphHandlers(
            compiler_data=compiler_data,
            compiler_entrypoint=compiler_entrypoint,
        )
        result = ablation.execute_ablation(
            _plan("A9"),
            graph.mapping(),
            output_root=tmp_path / str(index),
            resume=False,
        ).results[0]

        assert contracts.StageName.LEANSTRAL in graph.calls
        leanstral = next(
            stage
            for stage in result.stages
            if stage.stage is contracts.StageName.LEANSTRAL
        )
        assert leanstral.provenance.effective_identity["graph_invoked"] is True
        assert leanstral.data["proof_success"] is True
        assert result.status is contracts.OutcomeStatus.VERIFIED


@pytest.mark.parametrize(
    ("variant_id", "expected_proof_calls"),
    [
        (
            "A3",
            (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL),
        ),
        (
            "A4",
            (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL),
        ),
        (
            "A5",
            (contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL),
        ),
        ("A6", (contracts.StageName.LEANSTRAL,)),
        (
            "A12",
            (contracts.StageName.LEANSTRAL, contracts.StageName.HAMMER),
        ),
    ],
)
def test_compiler_native_candidate_does_not_change_other_arm_routing(
    tmp_path: Path,
    variant_id: str,
    expected_proof_calls: tuple[contracts.StageName, ...],
) -> None:
    graph = _GraphHandlers(
        compiler_data=_supported_runtime_compiler_data(),
    )
    result = ablation.execute_ablation(
        _plan(variant_id),
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]

    proof_calls = tuple(
        stage
        for stage in graph.calls
        if stage
        in {contracts.StageName.HAMMER, contracts.StageName.LEANSTRAL}
    )
    assert proof_calls == expected_proof_calls
    assert result.status is contracts.OutcomeStatus.VERIFIED
    assert result.validate_provenance() is None


def test_explicit_no_proof_target_records_zero_call_proof_and_kernel_gates(
    tmp_path: Path,
) -> None:
    graph = _GraphHandlers()
    plan = ablation.build_ablation_plan(
        "dataflow-no-proof",
        (_case(proof_obligation=False),),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=7,
        variant_ids=("A4",),
        cache_modes=(contracts.CacheMode.COLD,),
        environment_sha256="b" * 64,
    )
    result = ablation.execute_ablation(
        plan,
        graph.mapping(),
        output_root=tmp_path,
        resume=False,
    ).results[0]

    assert contracts.StageName.HAMMER not in graph.calls
    assert contracts.StageName.LEANSTRAL not in graph.calls
    assert contracts.StageName.KERNEL not in graph.calls
    for stage in result.stages:
        if stage.stage in {
            contracts.StageName.HAMMER,
            contracts.StageName.LEANSTRAL,
            contracts.StageName.KERNEL,
        }:
            assert stage.status is contracts.StageStatus.SUCCESS
            assert stage.data["invoked"] is False
            assert stage.data["reason"] == "no_reviewed_proof_obligation"
