"""Integration evidence for the exact frozen-arm runtime dataflow."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from benchmarks.logic_pipeline import ablation, adapters, contracts, variants


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
            "text": "Every reviewer is trained. Alice is a reviewer.",
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


class _GraphHandlers:
    def __init__(self, *, hammer_success: bool = False) -> None:
        self.calls: list[contracts.StageName] = []
        self.requests: dict[contracts.StageName, adapters.StageRequest] = {}
        self.hammer_success = hammer_success

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
                    }
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
                return adapters.StageOutput(
                    data={
                        "accepted": True,
                        "consumed": [
                            artifact.digest
                            for artifact in request.upstream_artifacts
                        ],
                    },
                    kernel_accepted=True,
                    kernel_receipt_sha256="c" * 64,
                )
            return adapters.StageOutput(data={"stage": stage.value})

        return invoke


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
