from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import time
from types import MappingProxyType

import pytest

from benchmarks.logic_pipeline import report, runner
from benchmarks.logic_pipeline.adapters import StageAdapter, StageOutput
from benchmarks.logic_pipeline.capabilities import (
    HSSLEV0118D14,
    WORKTREE_SAFETY_SCHEMA,
    WorktreeSafetyReceipt,
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
)


SHA_ENVIRONMENT = hashlib.sha256(b"pinned environment").hexdigest()
SHA_DRIFTED_ENVIRONMENT = hashlib.sha256(b"drifted environment").hexdigest()
SHA_MANIFEST = hashlib.sha256(b"failure-isolation cases").hexdigest()
SHA_KERNEL_RECEIPT = hashlib.sha256(b"accepted kernel receipt").hexdigest()
SOURCE_COMMIT = "1" * 40


def _cases(*case_ids: str) -> tuple[runner.AblationCase, ...]:
    return tuple(
        runner.AblationCase.create(
            case_id,
            {"case_id": case_id, "text": f"input for {case_id}"},
            split=Split.PILOT,
        )
        for case_id in case_ids
    )


def _plan(
    run_id: str,
    cases: tuple[runner.AblationCase, ...],
    *,
    environment_sha256: str = SHA_ENVIRONMENT,
    variant_id: str = "A0",
) -> runner.AblationPlan:
    return runner.build_ablation_plan(
        run_id,
        cases,
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=70,
        variant_ids=(variant_id,),
        cache_modes=(CacheMode.COLD,),
        environment_sha256=environment_sha256,
        limits=runner.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=2,
            max_memory_bytes=64 * 1024 * 1024,
            max_model_calls_per_case=1,
            max_solver_processes_per_case=1,
        ),
    )


def _worktree_receipt(tmp_path: Path, run_id: str) -> WorktreeSafetyReceipt:
    source = tmp_path / "active-source"
    common = tmp_path / "git-common"
    state = tmp_path / "benchmark-state" / run_id
    worktree = state / "worktrees" / "source"
    source.mkdir()
    common.mkdir()
    worktree.mkdir(parents=True)
    return WorktreeSafetyReceipt(
        schema=WORKTREE_SAFETY_SCHEMA,
        run_id=run_id,
        evidence=HSSLEV0118D14(),
        source_checkout=source,
        source_git_common_dir=common,
        source_head=SOURCE_COMMIT,
        source_branch="refs/heads/main",
        source_status_sha256=hashlib.sha256(b"clean").hexdigest(),
        base_revision=SOURCE_COMMIT,
        base_commit=SOURCE_COMMIT,
        worktree_root=worktree,
        worktree_commit=SOURCE_COMMIT,
        state_root=state,
        submodule_commits=MappingProxyType({}),
        detached=True,
        auto_merge=False,
        source_unchanged=True,
    )


def _run_replay_pair(
    tmp_path: Path,
    *,
    replay_environment: str = SHA_ENVIRONMENT,
    replay_backend_drift: bool = False,
) -> tuple[
    CaseResultRecord,
    CaseResultRecord,
    object,
    object,
    WorktreeSafetyReceipt,
]:
    case = _cases("replay-case")

    def adapters(*, drift: bool = False):
        result = {}
        for stage in (StageName.COMPILER, StageName.SPACY, StageName.KERNEL):
            def handler(request, current_stage=stage):
                data = {
                    "normalized": request.case_id,
                    "stable": True,
                    "stage": current_stage.value,
                }
                identity = dict(request.requested_identity)
                if drift and current_stage is StageName.SPACY:
                    identity["backend_revision"] = "drifted"
                return StageOutput(
                    data=data,
                    effective_identity=identity,
                    kernel_accepted=current_stage is StageName.KERNEL,
                    kernel_receipt_sha256=(
                        SHA_KERNEL_RECEIPT
                        if current_stage is StageName.KERNEL
                        else None
                    ),
                )

            result[stage] = StageAdapter(stage, handler)
        return result

    source_run = runner.execute_ablation(
        _plan("source-replay", case, variant_id="A1"),
        adapters(),
        output_root=tmp_path / "source-output",
        resume=False,
    )
    replay_run = runner.execute_ablation(
        _plan(
            "fresh-replay",
            case,
            environment_sha256=replay_environment,
            variant_id="A1",
        ),
        adapters(drift=replay_backend_drift),
        output_root=tmp_path / "replay-output",
        resume=False,
    )
    return (
        source_run.results[0],
        replay_run.results[0],
        source_run.contracts[0],
        replay_run.contracts[0],
        _worktree_receipt(tmp_path, "fresh-replay"),
    )


def test_injected_failures_are_classified_bounded_and_local(
    tmp_path: Path,
) -> None:
    kinds = {
        "missing-tool": (
            report.FailureInjectionKind.MISSING_TOOL,
            FailureCode.CAPABILITY_UNAVAILABLE,
        ),
        "malformed-output": (
            report.FailureInjectionKind.MALFORMED_OUTPUT,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        ),
        "timeout": (
            report.FailureInjectionKind.TIMEOUT,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        ),
        "cancellation": (
            report.FailureInjectionKind.CANCELLATION,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        ),
        "cache-corruption": (
            report.FailureInjectionKind.CACHE_CORRUPTION,
            FailureCode.CACHE_CONTAMINATION,
        ),
        "backend-drift": (
            report.FailureInjectionKind.BACKEND_DRIFT,
            FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        ),
    }
    case_ids = (*kinds, "healthy-case")

    def handler(request):
        if request.case_id == "healthy-case":
            return {"case_id": request.case_id, "healthy": True}
        kind, code = kinds[request.case_id]
        if kind is report.FailureInjectionKind.MISSING_TOOL:
            return StageOutput(
                status=StageStatus.UNAVAILABLE,
                failure_code=code,
                failure_detail="injected missing compiler",
            )
        if kind is report.FailureInjectionKind.MALFORMED_OUTPUT:
            return {"not-json-serializable"}  # runner must retain this exception
        return StageOutput(
            status=StageStatus.FAILED,
            failure_code=code,
            failure_detail=f"injected {kind.value}",
        )

    run = runner.execute_ablation(
        _plan("failure-matrix", _cases(*case_ids)),
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
        output_root=tmp_path / "matrix",
        resume=False,
    )
    by_case = {result.case_id: result for result in run.results}

    assert len(by_case) == len(case_ids)
    assert by_case["healthy-case"].status is OutcomeStatus.NOT_VERIFIED
    assert all(path.is_file() for path in run.result_paths)

    records = []
    for case_id, (kind, code) in kinds.items():
        result = by_case[case_id]
        assert result.failure_code is code
        record = report.FailureIsolationRecord.classify(
            f"inject-{case_id}",
            kind,
            result,
            elapsed_seconds=0.01,
            limit_seconds=1.0,
            affected_case_ids=(case_id,),
        )
        assert record.case_id == case_id
        assert record.stop_required is (
            kind
            in {
                report.FailureInjectionKind.CACHE_CORRUPTION,
                report.FailureInjectionKind.BACKEND_DRIFT,
            }
        )
        records.append(record)

    with pytest.raises(report.RobustnessValidationError, match="exactly its own"):
        report.FailureIsolationRecord.classify(
            "leaky-failure",
            report.FailureInjectionKind.CANCELLATION,
            by_case["cancellation"],
            elapsed_seconds=0.01,
            limit_seconds=1,
            affected_case_ids=("cancellation", "healthy-case"),
        )


def test_failed_stage_short_circuits_its_case_but_not_the_next_case(
    tmp_path: Path,
) -> None:
    calls: list[tuple[StageName, str]] = []

    def compiler(request):
        calls.append((StageName.COMPILER, request.case_id))
        if request.case_id == "failed-case":
            return StageOutput(
                status=StageStatus.FAILED,
                failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                failure_detail="injected compiler failure",
            )
        return {"compiled": request.case_id}

    def spacy(request):
        calls.append((StageName.SPACY, request.case_id))
        return {"parsed": request.case_id}

    plan = runner.build_ablation_plan(
        "short-circuit",
        _cases("failed-case", "healthy-case"),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=3,
        variant_ids=("A1",),
        cache_modes=(CacheMode.COLD,),
        environment_sha256=SHA_ENVIRONMENT,
    )
    run = runner.execute_ablation(
        plan,
        {
            StageName.COMPILER: StageAdapter(StageName.COMPILER, compiler),
            StageName.SPACY: StageAdapter(StageName.SPACY, spacy),
        },
        output_root=tmp_path,
        resume=False,
    )

    assert (StageName.SPACY, "failed-case") not in calls
    assert (StageName.SPACY, "healthy-case") in calls
    assert len(run.results) == 2


def test_timeout_and_explicit_cancellation_kill_the_process_group() -> None:
    program = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True);time.sleep(30)"
    )
    timed_out = report.run_bounded_process(
        (sys.executable, "-c", program),
        timeout_seconds=0.15,
        termination_grace_seconds=0.2,
    )

    assert timed_out.timed_out
    assert not timed_out.cancelled
    assert timed_out.failure_code is FailureCode.RESOURCE_LEASE_CANCELLATION
    assert timed_out.orphaned_child_count == 0
    assert timed_out.bounded
    assert report.BoundedProcessResult.from_dict(timed_out.to_dict()) == timed_out
    assert len(timed_out.digest) == 64
    child_pid = int(timed_out.stdout.strip())
    assert child_pid != timed_out.pid
    assert not Path(f"/proc/{child_pid}").exists() or (
        Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8").split()[2]
        == "Z"
    )

    class CancelSoon:
        def __init__(self) -> None:
            self.started = time.monotonic()

        def is_set(self) -> bool:
            return time.monotonic() - self.started >= 0.08

    cancelled = report.run_bounded_process(
        (sys.executable, "-c", "import time;time.sleep(30)"),
        timeout_seconds=2,
        cancellation=CancelSoon(),
        termination_grace_seconds=0.2,
    )
    assert cancelled.cancelled
    assert not cancelled.timed_out
    assert cancelled.failure_code is FailureCode.RESOURCE_LEASE_CANCELLATION
    assert cancelled.orphaned_child_count == 0
    assert cancelled.bounded


def test_normally_exiting_parent_cannot_hide_an_orphaned_child() -> None:
    program = (
        "import subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True)"
    )
    result = report.run_bounded_process(
        (sys.executable, "-c", program),
        timeout_seconds=1,
        termination_grace_seconds=0.2,
    )

    assert not result.timed_out
    assert not result.cancelled
    assert result.failure_code is FailureCode.ORPHANED_CHILD
    assert result.orphaned_child_count == 1
    child_pid = int(result.stdout.strip())
    assert not Path(f"/proc/{child_pid}").exists() or (
        Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8").split()[2]
        == "Z"
    )


def test_successful_receipt_replays_in_fresh_worktree_and_cold_cache(
    tmp_path: Path,
) -> None:
    original, replayed, original_contract, replay_contract, worktree = (
        _run_replay_pair(tmp_path)
    )

    replay = report.validate_replay(
        original,
        replayed,
        original_contract=original_contract,
        replay_contract=replay_contract,
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=worktree,
        expected_source_commit=SOURCE_COMMIT,
    )

    assert replay.status is report.ReplayStatus.PASSED
    assert original.status is OutcomeStatus.VERIFIED
    assert replayed.status is OutcomeStatus.VERIFIED
    assert replayed.kernel_receipt_sha256 == SHA_KERNEL_RECEIPT
    assert replay.original_run_id != replay.replay_run_id
    assert replay.original_cache_namespace != replay.replay_cache_namespace
    assert replay.source_commit == worktree.worktree_commit
    assert replay.environment_sha256 == SHA_ENVIRONMENT
    assert replay.original_receipt_sha256 != replay.replay_receipt_sha256
    assert report.ReplayValidationRecord.from_dict(replay.to_dict()) == replay


def test_corrupt_stale_and_backend_drifted_receipts_fail_closed(
    tmp_path: Path,
) -> None:
    original, replayed, original_contract, replay_contract, worktree = (
        _run_replay_pair(tmp_path)
    )
    corrupted = replayed.to_dict()
    corrupted["stages"][0]["data"]["stable"] = False
    with pytest.raises(ProtocolContractError, match="output_sha256"):
        CaseResultRecord.from_dict(corrupted)

    stale_pair = _run_replay_pair(
        tmp_path / "stale",
        replay_environment=SHA_DRIFTED_ENVIRONMENT,
    )
    with pytest.raises(report.RobustnessValidationError, match="stale"):
        report.validate_replay(
            stale_pair[0],
            stale_pair[1],
            original_contract=stale_pair[2],
            replay_contract=stale_pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=stale_pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )

    drift_pair = _run_replay_pair(
        tmp_path / "drift",
        replay_backend_drift=True,
    )
    with pytest.raises(report.RobustnessValidationError, match="drift"):
        report.validate_replay(
            drift_pair[0],
            drift_pair[1],
            original_contract=drift_pair[2],
            replay_contract=drift_pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=drift_pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )

    same_cache_contract = original_contract
    with pytest.raises(report.RobustnessValidationError, match="contract|fresh"):
        report.validate_replay(
            original,
            replayed,
            original_contract=original_contract,
            replay_contract=same_cache_contract,
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=worktree,
            expected_source_commit=SOURCE_COMMIT,
        )


def test_complete_robustness_report_is_strict_canonical_and_immutable(
    tmp_path: Path,
) -> None:
    case_ids = tuple(kind.value for kind in report.FailureInjectionKind)

    def handler(request):
        kind = report.FailureInjectionKind(request.case_id)
        code = {
            report.FailureInjectionKind.MISSING_TOOL: FailureCode.CAPABILITY_UNAVAILABLE,
            report.FailureInjectionKind.MALFORMED_OUTPUT: (
                FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
            ),
            report.FailureInjectionKind.TIMEOUT: FailureCode.RESOURCE_LEASE_CANCELLATION,
            report.FailureInjectionKind.CANCELLATION: FailureCode.RESOURCE_LEASE_CANCELLATION,
            report.FailureInjectionKind.CACHE_CORRUPTION: FailureCode.CACHE_CONTAMINATION,
            report.FailureInjectionKind.BACKEND_DRIFT: FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        }[kind]
        return StageOutput(
            status=(
                StageStatus.UNAVAILABLE
                if kind is report.FailureInjectionKind.MISSING_TOOL
                else StageStatus.FAILED
            ),
            failure_code=code,
            failure_detail=f"injected {kind.value}",
        )

    run = runner.execute_ablation(
        _plan("report-matrix", _cases(*case_ids)),
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
        output_root=tmp_path / "matrix",
        resume=False,
    )
    by_case = {item.case_id: item for item in run.results}
    failures = tuple(
        report.FailureIsolationRecord.classify(
            f"inject-{kind.value}",
            kind,
            by_case[kind.value],
            elapsed_seconds=0.01,
            limit_seconds=1,
            affected_case_ids=(kind.value,),
        )
        for kind in report.FailureInjectionKind
    )
    replay_pair = _run_replay_pair(tmp_path / "replay")
    replay = report.validate_replay(
        replay_pair[0],
        replay_pair[1],
        original_contract=replay_pair[2],
        replay_contract=replay_pair[3],
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=replay_pair[4],
        expected_source_commit=SOURCE_COMMIT,
    )
    robustness = report.RobustnessReport.create(failures, (replay,))
    encoded = report.canonical_robustness_report_json(robustness)
    report_path = report.write_robustness_report(
        robustness,
        tmp_path / "report" / "robustness.json",
    )

    assert report.HSSLEV0702E85() == (
        "failure injection, bounded isolation, and pinned fresh-worktree receipt replay"
    )
    assert report.RobustnessReport.from_dict(json.loads(encoded)) == robustness
    assert report.load_robustness_report(report_path) == robustness
    assert len(robustness.digest) == 64
    assert robustness.stop_required
    with pytest.raises(FrozenInstanceError):
        robustness.evidence = "changed"  # type: ignore[misc]

    unknown = json.loads(encoded)
    unknown["unexpected"] = True
    with pytest.raises(report.RobustnessValidationError, match="fields changed"):
        report.RobustnessReport.from_dict(unknown)
    with pytest.raises(report.RobustnessValidationError, match="each preregistered"):
        report.RobustnessReport.create(failures[:-1], (replay,))
    with pytest.raises(report.RobustnessValidationError, match="overwrite"):
        report.write_robustness_report(robustness, report_path)

    report_path.write_text(encoded, encoding="utf-8")
    with pytest.raises(report.RobustnessValidationError, match="newline"):
        report.load_robustness_report(report_path)
