from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import runner
from benchmarks.logic_pipeline.adapters import StageAdapter, StageOutput
from benchmarks.logic_pipeline.contracts import CacheMode, Split, StageName


SHA_MANIFEST = hashlib.sha256(b"cache-isolation-cases").hexdigest()
SHA_ENVIRONMENT = hashlib.sha256(b"pinned-cache-environment").hexdigest()


def _cases(count: int = 4) -> tuple[runner.AblationCase, ...]:
    return tuple(
        runner.AblationCase.create(
            f"cache-case-{index}",
            {"case_id": f"cache-case-{index}", "text": f"input {index}"},
            split=Split.PILOT,
        )
        for index in range(count)
    )


def _plan(
    *,
    run_id: str = "cache-isolation",
    seed: int = 71,
    environment_sha256: str | None = SHA_ENVIRONMENT,
    variants: tuple[str, ...] = ("A0", "A1", "A2"),
) -> runner.AblationPlan:
    return runner.build_ablation_plan(
        run_id,
        _cases(),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=seed,
        variant_ids=variants,
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
        environment_sha256=environment_sha256,
        limits=runner.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=2,
            max_memory_bytes=64 * 1024 * 1024,
            max_model_calls_per_case=2,
            max_solver_processes_per_case=1,
        ),
    )


def _adapters(
    *,
    drift_warm: bool = False,
    operational_cache_identity: bool = False,
    unrecognized_cache_prime_drift: bool = False,
) -> dict[StageName, StageAdapter]:
    adapters: dict[StageName, StageAdapter] = {}
    for stage in StageName:
        def handler(request, current=stage):
            identity = dict(request.requested_identity)
            identity["backend_revision"] = (
                "drifted"
                if drift_warm and request.cache_mode is CacheMode.WARM
                else "pinned"
            )
            if operational_cache_identity:
                identity.update(
                    {
                        "cache_namespace": (
                            f"{request.run_id}/{request.cache_mode.value}"
                        ),
                        "cache_key": (
                            f"{request.case_id}/{request.cache_mode.value}"
                        ),
                        "cache_hit": request.cache_mode is CacheMode.WARM,
                        "router_cache": request.cache_mode.value,
                        "router_cache_key": request.cache_mode.value,
                        "router_cached_backend": (
                            "pinned"
                            if request.cache_mode is CacheMode.WARM
                            else None
                        ),
                        "semantic_context_sha256": hashlib.sha256(
                            f"semantic:{request.cache_mode.value}".encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                        "premise_selection_sha256": hashlib.sha256(
                            f"premises:{request.cache_mode.value}".encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                        "generation_boundary_sha256": hashlib.sha256(
                            f"generation:{request.cache_mode.value}".encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    }
                )
            if unrecognized_cache_prime_drift:
                identity["cache_prime_effective_provider"] = (
                    "drifted"
                    if request.cache_mode is CacheMode.WARM
                    else "pinned"
                )
            return StageOutput(
                data={"case_id": request.case_id, "stage": current.value},
                effective_identity=identity,
            )

        adapters[stage] = StageAdapter(stage, handler)
    return adapters


def test_cache_evidence_namespaces_and_scope_receipts_bind_all_identities(
    tmp_path: Path,
) -> None:
    assert callable(runner.HSSLEV0717A46)
    plan = _plan(variants=("A0", "A1"))
    execution = runner.execute_ablation(
        plan,
        _adapters(),
        output_root=tmp_path,
        resume=False,
    )
    report = runner.validate_cache_isolation(execution)

    assert report.environment_sha256 == SHA_ENVIRONMENT
    assert report.plan_sha256 == plan.digest
    assert len(report.pairs) == len(plan.case_ids) * len(plan.variant_ids)
    assert len(report.cache_namespaces) == 4
    assert len(set(report.cache_namespaces)) == 4
    assert len(report.digest) == 64
    assert report.execution_order == tuple(job.job_id for job in plan.jobs)
    restored = runner.CacheIsolationReport.from_dict(report.to_dict())
    assert restored.to_dict() == report.to_dict()
    assert restored.digest == report.digest

    for contract in execution.contracts:
        scope_path = (
            tmp_path
            / "cache"
            / contract.split.value
            / contract.cache_mode.value
            / contract.requested_variant_id
            / "scope.json"
        )
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        assert scope["plan_sha256"] == plan.digest
        assert scope["environment_sha256"] == SHA_ENVIRONMENT
        assert scope["configuration_sha256"] == contract.configuration_sha256
        assert scope["cache_namespace"] == contract.cache_namespace
        assert scope["canonical_root"] == scope_path.parent.relative_to(
            tmp_path
        ).as_posix()


def test_schedule_is_seeded_recorded_and_position_counterbalanced() -> None:
    first = _plan(seed=700)
    replay = _plan(seed=700)
    other = _plan(seed=701)

    assert first.to_dict() == replay.to_dict()
    assert tuple(job.job_id for job in first.jobs) != tuple(
        job.job_id for job in other.jobs
    )
    assert tuple(job.ordinal for job in first.jobs) == tuple(
        range(len(first.jobs))
    )
    positions = {
        variant: [0 for _ in first.variant_ids]
        for variant in first.variant_ids
    }
    for block in first.blocks:
        assert {job.cache_mode for job in block} in (
            {CacheMode.COLD},
            {CacheMode.WARM},
        )
        for position, job in enumerate(block):
            positions[job.variant_id][position] += 1
    assert all(max(counts) - min(counts) <= 1 for counts in positions.values())


def test_backend_or_model_drift_invalidates_cache_comparison(
    tmp_path: Path,
) -> None:
    plan = _plan(variants=("A0",))
    execution = runner.execute_ablation(
        plan,
        _adapters(drift_warm=True),
        output_root=tmp_path,
        resume=False,
    )

    with pytest.raises(runner.CacheIsolationError, match="identity drifted"):
        runner.validate_cache_isolation(execution)


def test_operational_cache_envelopes_do_not_look_like_backend_drift(
    tmp_path: Path,
) -> None:
    plan = _plan(variants=("A0",))
    execution = runner.execute_ablation(
        plan,
        _adapters(operational_cache_identity=True),
        output_root=tmp_path,
        resume=False,
    )

    report = runner.validate_cache_isolation(execution)
    assert len(report.pairs) == len(plan.case_ids)


def test_unrecognized_cache_prime_identity_field_cannot_mask_backend_drift(
    tmp_path: Path,
) -> None:
    plan = _plan(variants=("A0",))
    execution = runner.execute_ablation(
        plan,
        _adapters(unrecognized_cache_prime_drift=True),
        output_root=tmp_path,
        resume=False,
    )

    with pytest.raises(runner.CacheIsolationError, match="identity drifted"):
        runner.validate_cache_isolation(execution)


def test_missing_environment_identity_cannot_enter_cache_comparison(
    tmp_path: Path,
) -> None:
    plan = _plan(environment_sha256=None, variants=("A0",))
    execution = runner.execute_ablation(
        plan,
        _adapters(),
        output_root=tmp_path,
        resume=False,
    )
    with pytest.raises(runner.CacheIsolationError, match="pinned environment"):
        runner.validate_cache_isolation(execution)


def test_cold_and_warm_records_remain_separate_and_resume_immutable(
    tmp_path: Path,
) -> None:
    plan = _plan(variants=("A0",))
    first = runner.execute_ablation(
        plan,
        _adapters(),
        output_root=tmp_path,
        resume=False,
    )
    before = {
        path: path.read_bytes() for path in first.result_paths
    }
    resumed = runner.execute_ablation(
        plan,
        _adapters(),
        output_root=tmp_path,
        resume=True,
    )

    assert not resumed.executed_job_ids
    assert len(resumed.resumed_job_ids) == len(plan.jobs)
    assert {
        result.cache_mode for result in resumed.results
    } == {CacheMode.COLD, CacheMode.WARM}
    assert len(
        {
            (result.case_id, result.variant_id, result.cache_mode)
            for result in resumed.results
        }
    ) == len(resumed.results)
    assert {path: path.read_bytes() for path in resumed.result_paths} == before
    runner.validate_cache_isolation(resumed)


def test_cache_symlink_escape_fails_before_adapter_invocation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    outside = tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    (output / "cache").symlink_to(outside, target_is_directory=True)
    calls: list[str] = []
    adapters = {
        StageName.COMPILER: StageAdapter(
            StageName.COMPILER,
            lambda request: calls.append(request.case_id) or {},
        )
    }

    with pytest.raises(
        runner.AblationValidationError,
        match="resolves outside",
    ):
        runner.execute_ablation(
            _plan(variants=("A0",)),
            adapters,
            output_root=output,
            resume=False,
        )
    assert not calls
