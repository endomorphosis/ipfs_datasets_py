from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import runner
from benchmarks.logic_pipeline import variants
from benchmarks.logic_pipeline.adapters import StageAdapter, StageOutput
from benchmarks.logic_pipeline.cases import (
    case_sha256,
    corpus_manifest_sha256,
    load_unsealed_pilot_development,
)
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CaseResultRecord,
    FailureCode,
    OutcomeStatus,
    ProtocolContractError,
    Split,
    StageName,
    StageStatus,
    TelemetryRecord,
)


EXPECTED_VARIANT_IDS = tuple([*(f"A{index}" for index in range(13)), "S1"])


def _pilot_cases(count: int = 2) -> tuple[runner.AblationCase, ...]:
    _manifest, unsealed = load_unsealed_pilot_development()
    selected = tuple(
        case for case in unsealed if case.split.value == Split.PILOT.value
    )[:count]
    return tuple(
        runner.AblationCase.create(
            case.case_id,
            input_data={
                "text": case.source_text,
                "source_sha256": case.source_sha256,
            },
            split=Split.PILOT,
            case_sha256=case_sha256(case),
        )
        for case in selected
    )


def _case_manifest_sha256() -> str:
    manifest, _unsealed = load_unsealed_pilot_development()
    return corpus_manifest_sha256(manifest)


class _RecordingHandlers:
    def __init__(
        self,
        *,
        fail_case_id: str | None = None,
        unavailable_stage: StageName | None = None,
    ) -> None:
        self.calls: list[tuple[StageName, str, str, CacheMode, str]] = []
        self.fail_case_id = fail_case_id
        self.unavailable_stage = unavailable_stage

    def adapters(self) -> Mapping[StageName, StageAdapter]:
        adapters: dict[StageName, StageAdapter] = {}
        for stage in StageName:
            adapters[stage] = StageAdapter(stage, handler=self._handler(stage))
        return MappingProxyType(adapters)

    def _handler(self, stage: StageName):
        def handle(request):
            self.calls.append(
                (
                    stage,
                    request.case_id,
                    request.variant_id,
                    request.cache_mode,
                    request.input_sha256,
                )
            )
            if request.case_id == self.fail_case_id and stage is StageName.COMPILER:
                raise RuntimeError("deliberate backend failure")
            if stage is self.unavailable_stage:
                from benchmarks.logic_pipeline.adapters import StageOutput

                return StageOutput(
                    status=StageStatus.UNAVAILABLE,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                    failure_detail=f"{stage.value} deliberately unavailable",
                )
            return {
                "case_id": request.case_id,
                "variant_id": request.variant_id,
                "stage": stage.value,
            }

        return handle


def _plan(
    *,
    run_id: str = "runner-integration",
    seed: int = 8675309,
    variant_ids: tuple[str, ...] = ("A0", "A4", "S1"),
    cache_modes: tuple[CacheMode, ...] = (CacheMode.COLD,),
    cases: tuple[runner.AblationCase, ...] | None = None,
) -> runner.AblationPlan:
    return runner.build_ablation_plan(
        run_id,
        _pilot_cases() if cases is None else cases,
        case_manifest_sha256=_case_manifest_sha256(),
        split=Split.PILOT,
        seed=seed,
        variant_ids=variant_ids,
        cache_modes=cache_modes,
        limits=runner.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=30,
            max_memory_bytes=256 * 1024 * 1024,
            max_model_calls_per_case=2,
            max_solver_processes_per_case=2,
        ),
    )


def _result_path(
    output_root: Path, job: runner.ScheduledCase
) -> Path:
    return (
        output_root
        / "results"
        / job.case.split.value
        / job.cache_mode.value
        / job.variant_id
        / f"{job.case.case_id}.json"
    )


def test_variant_registry_is_complete_explicit_stage_aware_and_immutable() -> None:
    assert callable(runner.HSSLEV0501F2F)
    assert variants.ALL_VARIANT_IDS == EXPECTED_VARIANT_IDS
    assert tuple(variants.VARIANT_REGISTRY) == EXPECTED_VARIANT_IDS
    assert set(variants.VARIANT_REGISTRY) == {
        item.variant_id for item in runner.DEFAULT_PROTOCOL.variants
    }

    for variant_id, definition in variants.VARIANT_REGISTRY.items():
        assert variants.get_variant_definition(variant_id) is definition
        assert definition.variant_id == variant_id
        assert definition.stages
        assert len(definition.stages) == len(set(definition.stages))
        assert tuple(StageName).index(definition.stages[0]) >= 0
        assert [tuple(StageName).index(item) for item in definition.stages] == sorted(
            tuple(StageName).index(item) for item in definition.stages
        )
        if StageName.KERNEL in definition.stages:
            assert definition.stages[-1] is StageName.KERNEL
        assert definition.to_dict()["required_capabilities"] == list(
            definition.required_capabilities
        )
        assert len(definition.digest) == 64

    assert variants.VARIANT_REGISTRY["A0"].stages == (StageName.COMPILER,)
    assert variants.VARIANT_REGISTRY["A6"].proof_order == (
        StageName.LEANSTRAL,
        StageName.HAMMER,
    )
    assert variants.VARIANT_REGISTRY["A9"].hammer_policy is variants.HammerPolicy.OFF
    assert variants.VARIANT_REGISTRY["A11"].premise_ranking is (
        variants.PremiseRanking.SYMAI_LLM
    )
    assert variants.VARIANT_REGISTRY["S1"].safety_diagnostic_only
    assert not variants.VARIANT_REGISTRY["S1"].primary_candidate

    with pytest.raises(TypeError):
        variants.VARIANT_REGISTRY["A0"] = variants.VARIANT_REGISTRY["A1"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        variants.VARIANT_REGISTRY["A0"].variant_id = "A1"  # type: ignore[misc]
    with pytest.raises(ProtocolContractError, match="not registered"):
        variants.get_variant_definition("A13")


def test_plan_pairs_identical_inputs_and_records_isolated_contracts() -> None:
    plan = _plan(
        variant_ids=EXPECTED_VARIANT_IDS,
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
    )

    assert plan.variant_ids == EXPECTED_VARIANT_IDS
    assert plan.seed == 8675309
    assert plan.limits.max_workers == 1
    assert len(plan.jobs) == len(_pilot_cases()) * 14 * 2
    assert len(plan.digest) == 64
    assert runner.AblationPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises(FrozenInstanceError):
        plan.seed = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.jobs[0].case.input_data["text"] = "changed"  # type: ignore[index]

    tampered = plan.to_dict()
    tampered["jobs"][0]["case"]["input_data"]["text"] = "changed"  # type: ignore[index]
    with pytest.raises(runner.AblationValidationError, match="digest changed"):
        runner.AblationPlan.from_dict(tampered)

    by_case_and_mode: dict[tuple[str, CacheMode], list[runner.ScheduledCase]] = {}
    for job in plan.jobs:
        by_case_and_mode.setdefault(
            (job.case.case_id, job.cache_mode), []
        ).append(job)
        assert job.input_sha256 == runner.AblationCase.create(
            job.case.case_id,
            input_data=job.case.to_dict()["input_data"],
            split=Split.PILOT,
            case_sha256=job.case.case_sha256,
        ).input_sha256

    for jobs in by_case_and_mode.values():
        assert {job.variant_id for job in jobs} == set(EXPECTED_VARIANT_IDS)
        assert len({job.input_sha256 for job in jobs}) == 1
        assert len({job.case.case_sha256 for job in jobs}) == 1

    namespaces = {
        runner.CacheScope(
            plan.run_id,
            plan.protocol_sha256,
            variant_id,
            plan.split,
            cache_mode,
        ).namespace
        for variant_id in plan.variant_ids
        for cache_mode in plan.cache_modes
    }
    assert len(namespaces) == 14 * 2
    assert all(plan.run_id in namespace for namespace in namespaces)


def test_randomized_block_order_is_seeded_reproducible_and_balanced() -> None:
    first = _plan(seed=41, variant_ids=("A0", "A1", "A4", "S1"))
    replay = _plan(seed=41, variant_ids=("A0", "A1", "A4", "S1"))
    other = _plan(seed=42, variant_ids=("A0", "A1", "A4", "S1"))

    assert first.to_dict() == replay.to_dict()
    assert first.digest == replay.digest
    assert tuple(job.ordinal for job in first.jobs) == tuple(
        range(len(first.jobs))
    )
    assert tuple(job.variant_id for job in first.jobs) != tuple(
        job.variant_id for job in other.jobs
    )

    for plan in (first, other):
        blocks: dict[tuple[str, CacheMode], list[runner.ScheduledCase]] = {}
        for job in plan.jobs:
            blocks.setdefault(
                (job.case.case_id, job.cache_mode), []
            ).append(job)
        assert all(
            {job.variant_id for job in block} == {"A0", "A1", "A4", "S1"}
            for block in blocks.values()
        )


def test_execute_uses_each_variants_explicit_route_and_requested_identity(
    tmp_path: Path,
) -> None:
    recorder = _RecordingHandlers()
    plan = _plan(variant_ids=EXPECTED_VARIANT_IDS)
    run = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=False
    )
    records = run.results

    assert run.plan == plan
    assert len(run.executed_job_ids) == len(plan.jobs)
    assert not run.resumed_job_ids
    assert run.complete
    assert len(records) == len(plan.jobs)
    assert len(run.contracts) == len(plan.variant_ids) * len(plan.cache_modes)
    assert len({contract.cache_namespace for contract in run.contracts}) == len(
        run.contracts
    )
    assert all(
        contract.requested_variant_id == contract.effective_variant_id
        for contract in run.contracts
    )
    by_identity = {
        (record.case_id, record.variant_id, record.cache_mode): record
        for record in records
    }
    for job in plan.jobs:
        definition = variants.VARIANT_REGISTRY[job.variant_id]
        record = by_identity[
            (job.case.case_id, job.variant_id, job.cache_mode)
        ]
        assert tuple(stage.stage for stage in record.stages) == definition.stages
        assert all(stage.variant_id == job.variant_id for stage in record.stages)
        assert all(
            stage.provenance.requested_identity["variant_id"] == job.variant_id
            for stage in record.stages
        )
        assert all(
            stage.provenance.effective_identity["variant_id"] == job.variant_id
            for stage in record.stages
        )
        assert record.status is OutcomeStatus.NOT_VERIFIED
        envelope = json.loads(
            _result_path(run.output_root, job).read_text(encoding="utf-8")
        )
        assert envelope["requested_configuration"] == definition.to_dict()
        assert [
            entry["stage"] for entry in envelope["effective_configuration"]
        ] == [stage.value for stage in definition.stages]


def test_recorded_resource_ceiling_converts_over_budget_job_to_a_result(
    tmp_path: Path,
) -> None:
    def model_handler(request):
        return StageOutput(
            data={"candidate": "bounded"},
            effective_identity=request.requested_identity,
            telemetry=TelemetryRecord(
                model_calls=3,
                resource_lane=runner.ResourceLane.MODEL,
            ),
        )

    adapters = dict(_RecordingHandlers().adapters())
    adapters[StageName.SYMAI] = StageAdapter(
        StageName.SYMAI, handler=model_handler
    )
    plan = _plan(variant_ids=("A4",), cases=_pilot_cases(1))
    run = runner.execute_ablation(
        plan, adapters, output_root=tmp_path, resume=False
    )

    assert len(run.results) == 1
    result = run.results[0]
    assert result.status is OutcomeStatus.INFRASTRUCTURE_FAILURE
    assert result.failure_code is FailureCode.RESOURCE_LEASE_CANCELLATION
    assert result.failure_detail == "model-call limit exceeded"
    assert _result_path(run.output_root, plan.jobs[0]).is_file()


def test_unavailable_capability_never_substitutes_or_erases_requested_arm(
    tmp_path: Path,
) -> None:
    recorder = _RecordingHandlers(unavailable_stage=StageName.SYMAI)
    plan = _plan(variant_ids=("A4",))
    run = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=False
    )
    records = run.results

    assert len(records) == len(plan.jobs)
    assert all(record.variant_id == "A4" for record in records)
    assert all(record.status is OutcomeStatus.UNAVAILABLE for record in records)
    for record in records:
        symai = next(stage for stage in record.stages if stage.stage is StageName.SYMAI)
        assert symai.status is StageStatus.UNAVAILABLE
        assert symai.failure_code is FailureCode.CAPABILITY_UNAVAILABLE
        assert symai.provenance.requested_identity["variant_id"] == "A4"


def test_backend_failure_is_durable_and_does_not_cancel_other_cases(
    tmp_path: Path,
) -> None:
    cases = _pilot_cases()
    recorder = _RecordingHandlers(fail_case_id=cases[0].case_id)
    plan = _plan(variant_ids=("A1",), cases=cases)
    run = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=False
    )
    records = run.results

    assert len(records) == 2
    failed = next(record for record in records if record.case_id == cases[0].case_id)
    succeeded = next(
        record for record in records if record.case_id == cases[1].case_id
    )
    assert failed.status is OutcomeStatus.INFRASTRUCTURE_FAILURE
    assert failed.failure_code is FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
    assert failed.stages[0].status is StageStatus.FAILED
    assert succeeded.status is OutcomeStatus.NOT_VERIFIED
    assert {record.case_id for record in records} == {
        cases[0].case_id,
        cases[1].case_id,
    }


def test_resume_skips_exact_completed_jobs_without_duplicate_invocations(
    tmp_path: Path,
) -> None:
    recorder = _RecordingHandlers()
    plan = _plan(variant_ids=("A0", "A1"))
    first = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=False
    )
    calls_after_first = tuple(recorder.calls)
    before = {
        job.job_id: _result_path(first.output_root, job).read_bytes()
        for job in plan.jobs
    }

    replay = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=True
    )

    assert not replay.executed_job_ids
    assert len(replay.resumed_job_ids) == len(plan.jobs)
    assert tuple(recorder.calls) == calls_after_first
    assert {
        job.job_id: _result_path(replay.output_root, job).read_bytes()
        for job in plan.jobs
    } == before
    records = replay.results
    identities = {
        (item.case_id, item.variant_id, item.cache_mode) for item in records
    }
    assert len(records) == len(identities) == len(plan.jobs)


@pytest.mark.parametrize("mutation", ["tamper", "duplicate", "foreign-plan"])
def test_resume_fails_closed_on_nonimmutable_or_conflicting_records(
    tmp_path: Path,
    mutation: str,
) -> None:
    recorder = _RecordingHandlers()
    plan = _plan(variant_ids=("A0",))
    first = runner.execute_ablation(
        plan, recorder.adapters(), output_root=tmp_path, resume=False
    )
    first_path = _result_path(first.output_root, plan.jobs[0])

    if mutation == "tamper":
        payload = json.loads(first_path.read_text(encoding="utf-8"))
        payload["case_result"]["stages"][0]["data"]["case_id"] = "tampered"
        first_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "duplicate":
        duplicate = first.output_root / "results" / "duplicate.json"
        duplicate.write_bytes(first_path.read_bytes())
    else:
        payload = json.loads(first_path.read_text(encoding="utf-8"))
        payload["plan_sha256"] = "0" * 64
        first_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    calls_before_resume = tuple(recorder.calls)
    with pytest.raises((runner.AblationValidationError, ProtocolContractError)):
        runner.execute_ablation(
            plan, recorder.adapters(), output_root=tmp_path, resume=True
        )
    assert tuple(recorder.calls) == calls_before_resume
