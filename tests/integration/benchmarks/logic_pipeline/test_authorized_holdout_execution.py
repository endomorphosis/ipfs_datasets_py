from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import ablation
from benchmarks.logic_pipeline.adapters import StageAdapter, StageOutput
from benchmarks.logic_pipeline.cases import load_reviewed_corpus
from benchmarks.logic_pipeline.contracts import CacheMode, StageName
from benchmarks.logic_pipeline.holdout_execution import (
    HSSLEV1167A17,
    HoldoutExecutionError,
    HoldoutExecutionReceipt,
    PilotAuthorizationReceipt,
    build_authorized_holdout_plan,
    build_holdout_access_audits,
    execute_authorized_holdout,
)


SOURCE_COMMIT = "1" * 40
ENVIRONMENT_SHA256 = hashlib.sha256(b"authorized environment").hexdigest()
PILOT_GATE_SHA256 = hashlib.sha256(b"passed source-bound pilot gate").hexdigest()
PROMPTS_SHA256 = hashlib.sha256(b"frozen prompts").hexdigest()
POLICY_SHA256 = hashlib.sha256(b"frozen policy").hexdigest()
MODELS_SHA256 = hashlib.sha256(b"frozen model identities").hexdigest()
THRESHOLDS_SHA256 = hashlib.sha256(b"frozen thresholds").hexdigest()


@pytest.fixture
def corpus():
    return load_reviewed_corpus()


@pytest.fixture
def authorization(corpus):
    return PilotAuthorizationReceipt.create(
        authorization_id="pilot-authorization-v2",
        pilot_run_id="pilot-reassessment-v2",
        pilot_gate_sha256=PILOT_GATE_SHA256,
        source_commit=SOURCE_COMMIT,
        environment_sha256=ENVIRONMENT_SHA256,
        corpus_manifest_sha256=corpus.manifest_sha256,
        holdout_split_sha256=corpus.split_integrity.holdout.split_sha256,
        shortlist_variant_ids=("A1",),
        prompts_sha256=PROMPTS_SHA256,
        policy_sha256=POLICY_SHA256,
        model_identities_sha256=MODELS_SHA256,
        thresholds_sha256=THRESHOLDS_SHA256,
    )


@pytest.fixture
def plan(corpus, authorization):
    return build_authorized_holdout_plan(
        authorization,
        corpus,
        run_id="authorized-holdout-v2",
        seed=1167,
        access_ledger_id="holdout-access-v2",
        limits=ablation.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=2,
            max_memory_bytes=64 * 1024 * 1024,
            max_model_calls_per_case=2,
            max_solver_processes_per_case=1,
        ),
    )


@pytest.fixture
def audits(corpus, authorization, plan):
    return build_holdout_access_audits(
        authorization,
        corpus,
        plan,
        prompt_examples={},
    )


def _adapters(calls: list[tuple[str, str]]) -> dict[StageName, StageAdapter]:
    adapters: dict[StageName, StageAdapter] = {}
    for stage in StageName:

        def handler(request, current=stage):
            calls.append((request.case_id, current.value))
            return StageOutput(
                data={"case_id": request.case_id, "stage": current.value},
                effective_identity=dict(request.requested_identity),
            )

        adapters[stage] = StageAdapter(stage, handler)
    return adapters


def test_authorized_holdout_executes_exact_frozen_pairs(
    tmp_path: Path, corpus, authorization, plan, audits
) -> None:
    calls: list[tuple[str, str]] = []
    output = tmp_path / "holdout"

    run = execute_authorized_holdout(
        authorization,
        corpus,
        plan,
        audits,
        _adapters(calls),
        source_commit=SOURCE_COMMIT,
        environment_sha256=ENVIRONMENT_SHA256,
        output_root=output,
    )

    assert callable(HSSLEV1167A17)
    assert plan.variant_ids == ("A0", "A1")
    assert plan.cache_modes == (CacheMode.COLD, CacheMode.WARM)
    assert plan.case_ids == corpus.split_integrity.holdout.case_ids
    assert len(plan.jobs) == len(plan.case_ids) * 2 * 2
    assert run.execution.complete is True
    assert len(run.execution.results) == len(plan.jobs)
    assert run.receipt.complete is True
    assert run.receipt.source_commit == SOURCE_COMMIT
    assert len(run.receipt.cache_namespaces) == 4
    assert len(set(run.receipt.cache_namespaces)) == 4
    assert HoldoutExecutionReceipt.from_dict(
        run.receipt.to_dict()
    ) == run.receipt
    assert (
        output / "state" / "holdout-authorization.json"
    ).is_file()
    assert (output / "state" / "holdout-access-audits.json").is_file()
    assert (
        output / "receipts" / "holdout-execution-receipt.json"
    ).is_file()
    assert calls

    positions = {
        variant: [0] * len(plan.variant_ids) for variant in plan.variant_ids
    }
    for block in plan.blocks:
        assert len({job.input_sha256 for job in block}) == 1
        assert {job.variant_id for job in block} == set(plan.variant_ids)
        for position, job in enumerate(block):
            positions[job.variant_id][position] += 1
    assert all(max(counts) - min(counts) <= 1 for counts in positions.values())
    block_pairs = tuple(
        plan.blocks[index : index + 2]
        for index in range(0, len(plan.blocks), 2)
    )
    assert all(
        pair[0][0].case.case_id == pair[1][0].case.case_id
        and {pair[0][0].cache_mode, pair[1][0].cache_mode}
        == {CacheMode.COLD, CacheMode.WARM}
        for pair in block_pairs
    )
    leading_modes = [pair[0][0].cache_mode for pair in block_pairs]
    assert abs(
        leading_modes.count(CacheMode.COLD)
        - leading_modes.count(CacheMode.WARM)
    ) <= 1


@pytest.mark.parametrize(
    ("source_commit", "environment_sha256", "purpose"),
    (
        ("2" * 40, ENVIRONMENT_SHA256, "evaluation"),
        (SOURCE_COMMIT, "3" * 64, "evaluation"),
        (SOURCE_COMMIT, ENVIRONMENT_SHA256, "replay"),
    ),
)
def test_drift_or_wrong_access_purpose_fails_before_write_or_backend(
    tmp_path: Path,
    corpus,
    authorization,
    plan,
    source_commit: str,
    environment_sha256: str,
    purpose: str,
) -> None:
    audits = build_holdout_access_audits(
        authorization,
        corpus,
        plan,
        prompt_examples={},
        purpose=purpose,
    )
    calls: list[tuple[str, str]] = []
    output = tmp_path / "must-not-exist"

    with pytest.raises(HoldoutExecutionError):
        execute_authorized_holdout(
            authorization,
            corpus,
            plan,
            audits,
            _adapters(calls),
            source_commit=source_commit,
            environment_sha256=environment_sha256,
            output_root=output,
        )

    assert calls == []
    assert not output.exists()


def test_missing_reordered_or_post_access_changed_audits_fail_closed(
    tmp_path: Path, corpus, authorization, plan, audits
) -> None:
    invalid_logs = (
        audits[:-1],
        tuple(reversed(audits)),
        build_holdout_access_audits(
            authorization,
            corpus,
            plan,
            prompt_examples={},
            purpose="replay",
        ),
    )
    for index, invalid in enumerate(invalid_logs):
        calls: list[tuple[str, str]] = []
        output = tmp_path / f"invalid-{index}"
        with pytest.raises(HoldoutExecutionError):
            execute_authorized_holdout(
                authorization,
                corpus,
                plan,
                invalid,
                _adapters(calls),
                source_commit=SOURCE_COMMIT,
                environment_sha256=ENVIRONMENT_SHA256,
                output_root=output,
            )
        assert calls == []
        assert not output.exists()


def test_generic_executor_and_existing_namespace_remain_fail_closed(
    tmp_path: Path, corpus, authorization, plan, audits
) -> None:
    calls: list[tuple[str, str]] = []
    generic_output = tmp_path / "generic"
    with pytest.raises(
        ablation.AblationValidationError, match="forbidden for holdout"
    ):
        ablation.execute_ablation(
            plan,
            _adapters(calls),
            output_root=generic_output,
        )
    assert calls == []
    assert not generic_output.exists()

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "operator-data"
    sentinel.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(HoldoutExecutionError, match="fresh"):
        execute_authorized_holdout(
            authorization,
            corpus,
            plan,
            audits,
            _adapters(calls),
            source_commit=SOURCE_COMMIT,
            environment_sha256=ENVIRONMENT_SHA256,
            output_root=occupied,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert calls == []


def test_authorization_is_strict_content_addressed_and_nonempty(
    corpus, authorization
) -> None:
    assert PilotAuthorizationReceipt.from_dict(
        authorization.to_dict()
    ) == authorization

    changed = authorization.to_dict()
    changed["source_commit"] = "9" * 40
    with pytest.raises(HoldoutExecutionError, match="authorization_sha256"):
        PilotAuthorizationReceipt.from_dict(changed)

    with pytest.raises(HoldoutExecutionError, match="one to four"):
        PilotAuthorizationReceipt.create(
            authorization_id="empty-shortlist",
            pilot_run_id="pilot-v2",
            pilot_gate_sha256=PILOT_GATE_SHA256,
            source_commit=SOURCE_COMMIT,
            environment_sha256=ENVIRONMENT_SHA256,
            corpus_manifest_sha256=corpus.manifest_sha256,
            holdout_split_sha256=corpus.split_integrity.holdout.split_sha256,
            shortlist_variant_ids=(),
            prompts_sha256=PROMPTS_SHA256,
            policy_sha256=POLICY_SHA256,
            model_identities_sha256=MODELS_SHA256,
            thresholds_sha256=THRESHOLDS_SHA256,
        )

    with pytest.raises(HoldoutExecutionError, match="requires passed=True"):
        replace(authorization, passed=False)
