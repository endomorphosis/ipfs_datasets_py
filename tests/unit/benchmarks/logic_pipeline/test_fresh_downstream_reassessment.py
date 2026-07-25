"""Synthetic, holdout-free coverage for the fresh downstream handoff."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import adapters
from benchmarks.logic_pipeline import holdout_reassessment
from benchmarks.logic_pipeline import reassessment_reports
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    AblationRunResult,
    _execute_ablation,
    build_ablation_plan,
)
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    HoldoutAccessAudit,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    CaseResultRecord,
    FailureCode,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.holdout_execution import (
    HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
    AuthorizedHoldoutRun,
    HSSLEV1167A17,
    HoldoutExecutionError,
    HoldoutExecutionReceipt,
)
from benchmarks.logic_pipeline.pilot_reassessment import (
    PILOT_REASSESSMENT_SCHEMA,
)
from benchmarks.logic_pipeline.reassessment_namespace import (
    ReassessmentRunLayout,
)
from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY_SHA256


RUN_ID = "synthetic-authorized-downstream"
SOURCE_COMMIT = "1" * 40


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _native_kernel_receipt(
    *,
    case_id: str,
    variant_id: str,
    cache_mode: CacheMode,
    input_sha256: str,
    environment_sha256: str,
    accepted: bool,
    candidate_artifact_sha256: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "native-kernel-receipt.v1"
        ),
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "run_id": RUN_ID,
        "case_id": case_id,
        "case_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "variant_id": variant_id,
        "split": Split.HOLDOUT.value,
        "cache_mode": cache_mode.value,
        "input_sha256": input_sha256,
        "environment_sha256": environment_sha256,
        "independent": True,
        "accepted": accepted,
        "active_process_count": 0,
    }
    if accepted:
        assert candidate_artifact_sha256 is not None
        attempt_body = {
            "attempt_index": 0,
            "candidate_source": StageName.COMPILER.value,
            "candidate_artifact_sha256": candidate_artifact_sha256,
            "source_sha256": hashlib.sha256(b"source").hexdigest(),
            "command_sha256": hashlib.sha256(b"command").hexdigest(),
            "stdout_sha256": hashlib.sha256(b"accepted").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
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
        body.update(
            {
                "compiled_obligation_sha256": _sha("compiled"),
                "obligation_sha256": _sha("obligation"),
                "candidate_source": attempt["candidate_source"],
                "candidate_artifact_sha256": candidate_artifact_sha256,
                "source_sha256": attempt["source_sha256"],
                "semantic_context_sha256": _sha("semantic-context"),
                "semantic_artifact_sha256s": [
                    candidate_artifact_sha256
                ],
                "command_sha256": attempt["command_sha256"],
                "stdout_sha256": attempt["stdout_sha256"],
                "stderr_sha256": attempt["stderr_sha256"],
                "returncode": attempt["returncode"],
                "timed_out": attempt["timed_out"],
                "cancelled": attempt["cancelled"],
                "resource_exhausted": attempt["resource_exhausted"],
                "termination_reason": attempt["termination_reason"],
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
        body["reason"] = "no_proof_candidate"
    return {**body, "receipt_sha256": _sha(body)}


def _authorized_pilot(environment_sha256: str) -> dict[str, object]:
    digest = lambda label: hashlib.sha256(label.encode("utf-8")).hexdigest()
    pilot: dict[str, object] = {
        "schema": PILOT_REASSESSMENT_SCHEMA,
        "run_id": RUN_ID,
        "status": "complete",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "candidate_evidence": [
            {
                "variant_id": "A1",
                "configuration_sha256": (
                    "c555856ea728946c965ee8aeecaf551623931a5a522851cef21ee51ed28c5b13"
                ),
                "eligible": True,
                "ineligibility_reasons": [],
            }
        ],
        "shortlist": {
            "status": "complete",
            "frozen": True,
            "selected_variant_ids": ["A1"],
            "selected_count": 1,
        },
        "holdout": {
            "status": "authorized_unopened",
            "authorized": True,
            "authorization_sha256": None,
            "outcomes_inspected": False,
        },
        "decision": {"status": "complete"},
        "deep_freeze": {
            "tuning_permitted": False,
            "freeze_sha256": digest("freeze"),
            "inputs": {
                "source": {"commit": SOURCE_COMMIT},
                "prompts": {"sha256": digest("prompts")},
                "policies": {"sha256": digest("policies")},
                "model_identities": {"sha256": digest("models")},
                "environment": {"sha256": environment_sha256},
                "resource_policy": {"sha256": digest("resources")},
                "thresholds": {"sha256": digest("thresholds")},
            },
        },
        "remediation": [],
        "artifact_sha256": "",
    }
    pilot["artifact_sha256"] = _sha(
        {key: value for key, value in pilot.items() if key != "artifact_sha256"}
    )
    return pilot


def _synthetic_authorized_run(
    pilot: dict[str, object],
    environment_sha256: str,
    *,
    output_root: Path,
    disproved_case_ordinals: tuple[int, ...] = (),
) -> AuthorizedHoldoutRun:
    authorization = holdout_reassessment._authorization_from_pilot(
        pilot,
        run_id=RUN_ID,
    )
    cases = tuple(
        AblationCase.create(
            f"synthetic-h{index:02d}",
            {
                "text": f"Synthetic unopened input {index}",
                "expected_class": (
                    "disproved"
                    if index in disproved_case_ordinals
                    else "unsupported"
                ),
            },
            split=Split.HOLDOUT,
        )
        for index in range(1, 11)
    )
    plan = build_ablation_plan(
        RUN_ID,
        cases,
        case_manifest_sha256=FROZEN_CORPUS_MANIFEST_SHA256,
        split=Split.HOLDOUT,
        seed=1507,
        variant_ids=("A0", "A1"),
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
        environment_sha256=environment_sha256,
        holdout_access_log_id="synthetic-access-ledger",
    )
    def handler(stage_name: StageName):
        def invoke(
            request: adapters.StageRequest,
        ) -> adapters.StageOutput:
            if stage_name is StageName.KERNEL:
                kernel_receipt = _native_kernel_receipt(
                    case_id=request.case_id,
                    variant_id=request.variant_id,
                    cache_mode=request.cache_mode,
                    input_sha256=request.input_sha256,
                    environment_sha256=environment_sha256,
                    accepted=False,
                )
                return adapters.StageOutput(data=kernel_receipt)
            return adapters.StageOutput(
                data={"stage": stage_name.value, "synthetic": True}
            )

        return invoke

    execution = _execute_ablation(
        plan,
        {
            stage: adapters.StageAdapter(
                stage,
                handler=handler(stage),
                source=("synthetic-holdout-fixture",),
            )
            for stage in StageName
        },
        output_root=output_root,
        resume=False,
        resource_scheduler=None,
        authorized_holdout=True,
    )
    results = execution.results
    audits = []
    for sequence, contract in enumerate(plan.run_contracts):
        audit_payload = {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "holdout-access.v1"
            ),
            "audit_id": contract.holdout_access_log_id,
            "sequence": sequence,
            "purpose": "evaluation",
            "run_contract_sha256": _sha(contract.to_dict()),
            "run_id": contract.run_id,
            "protocol_sha256": contract.protocol_sha256,
            "variant_id": contract.requested_variant_id,
            "cache_namespace": contract.cache_namespace,
            "cache_mode": contract.cache_mode.value,
            "corpus_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
            "holdout_split_sha256": FROZEN_SPLIT_SHA256[Split.HOLDOUT],
            "accessed_case_ids": list(plan.case_ids),
            "configuration_sha256": contract.configuration_sha256,
            "prompts_sha256": authorization.prompts_sha256,
            "policy_sha256": authorization.policy_sha256,
            "model_identities_sha256": (
                authorization.model_identities_sha256
            ),
            "thresholds_sha256": authorization.thresholds_sha256,
            "prompt_example_sha256s": [],
            "prompts_frozen": True,
            "policy_frozen": True,
            "model_identities_frozen": True,
            "thresholds_frozen": True,
            "tuning_permitted": False,
        }
        audits.append(
            HoldoutAccessAudit.from_dict(
                {
                    **audit_payload,
                    "audit_sha256": _sha(audit_payload),
                }
            )
        )
    access_audits = tuple(audits)
    receipt_payload = {
        "schema": HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "run_id": RUN_ID,
        "source_commit": SOURCE_COMMIT,
        "environment_sha256": environment_sha256,
        "authorization_sha256": authorization.authorization_sha256,
        "pilot_gate_sha256": authorization.pilot_gate_sha256,
        "plan_sha256": plan.digest,
        "access_audit_sha256s": tuple(
            item.audit_sha256 for item in access_audits
        ),
        "result_sha256s": tuple(item.digest for item in results),
        "cache_namespaces": tuple(
            contract.cache_namespace for contract in plan.run_contracts
        ),
        "executed_job_ids": execution.executed_job_ids,
        "complete": True,
    }
    receipt = HoldoutExecutionReceipt(
        **receipt_payload,
        receipt_sha256=_sha(
            {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in receipt_payload.items()
            }
        ),
    )
    return AuthorizedHoldoutRun(execution, receipt, access_audits)


def _rebind_authorized_run(
    authorized: AuthorizedHoldoutRun,
    *,
    execution: AblationRunResult | None = None,
    access_audits: tuple[HoldoutAccessAudit, ...] | None = None,
) -> AuthorizedHoldoutRun:
    rebound_execution = execution or authorized.execution
    rebound_audits = access_audits or authorized.access_audits
    receipt_payload = authorized.receipt.identity_payload()
    receipt_payload["result_sha256s"] = [
        item.digest for item in rebound_execution.results
    ]
    receipt_payload["access_audit_sha256s"] = [
        item.audit_sha256 for item in rebound_audits
    ]
    receipt = HoldoutExecutionReceipt.from_dict(
        {
            **receipt_payload,
            "receipt_sha256": _sha(receipt_payload),
        }
    )
    return AuthorizedHoldoutRun(
        rebound_execution,
        receipt,
        rebound_audits,
    )


def _accept_terminal_kernel(
    result: CaseResultRecord,
    *,
    environment_sha256: str,
) -> CaseResultRecord:
    kernel = result.stages[-1]
    assert kernel.stage is StageName.KERNEL
    consumed = tuple(
        kernel.provenance.effective_identity[
            "consumed_artifact_sha256"
        ]
    )
    assert consumed
    native_receipt = _native_kernel_receipt(
        case_id=result.case_id,
        variant_id=result.variant_id,
        cache_mode=result.cache_mode,
        input_sha256=kernel.provenance.input_sha256,
        environment_sha256=environment_sha256,
        accepted=True,
        candidate_artifact_sha256=consumed[-1],
    )
    accepted_kernel = StageRecord.create(
        protocol_sha256=kernel.protocol_sha256,
        run_id=kernel.run_id,
        case_id=kernel.case_id,
        case_manifest_sha256=kernel.case_manifest_sha256,
        variant_id=kernel.variant_id,
        split=kernel.split,
        cache_mode=kernel.cache_mode,
        stage=kernel.stage,
        adapter_version=kernel.adapter_version,
        status=StageStatus.SUCCESS,
        provenance=kernel.provenance,
        telemetry=kernel.telemetry,
        data=native_receipt,
        kernel_accepted=True,
        kernel_receipt_sha256=str(
            native_receipt["receipt_sha256"]
        ),
    )
    return CaseResultRecord.from_stages(
        (*result.stages[:-1], accepted_kernel)
    )


def _synthetic_reviewed_corpus(
    authorized: AuthorizedHoldoutRun,
) -> SimpleNamespace:
    jobs_by_case = {
        job.case_id: job for job in authorized.execution.plan.jobs
    }
    manifest = SimpleNamespace(
        cases=tuple(
            SimpleNamespace(
                split=Split.HOLDOUT,
                case_id=case_id,
                case_sha256=jobs_by_case[case_id].case_sha256,
                source_sha256=hashlib.sha256(
                    str(jobs_by_case[case_id].input_data["text"]).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            )
            for case_id in authorized.execution.plan.case_ids
        )
    )
    return SimpleNamespace(manifest=manifest)


def _install_synthetic_access_validator(
    monkeypatch,
    *,
    authorized: AuthorizedHoldoutRun,
    expected_access_audits: tuple[HoldoutAccessAudit, ...] | None = None,
) -> None:
    expected = expected_access_audits or authorized.access_audits

    def validate_access_audits(
        _authorization: object,
        _corpus: object,
        plan: object,
        audits: object,
        *,
        purpose: str,
    ) -> tuple[HoldoutAccessAudit, ...]:
        parsed = tuple(audits)
        if (
            plan != authorized.execution.plan
            or purpose != "evaluation"
            or tuple(item.to_dict() for item in parsed)
            != tuple(item.to_dict() for item in expected)
        ):
            raise HoldoutExecutionError(
                "synthetic access audit differs from its frozen contract"
            )
        return parsed

    monkeypatch.setattr(
        holdout_reassessment,
        "validate_holdout_access_audits",
        validate_access_audits,
    )


def _build_synthetic_authorized_report(
    tmp_path: Path,
    monkeypatch,
    *,
    pilot: dict[str, object],
    authorized: AuthorizedHoldoutRun,
    expected_access_audits: tuple[HoldoutAccessAudit, ...] | None = None,
) -> dict[str, object]:
    _install_synthetic_access_validator(
        monkeypatch,
        authorized=authorized,
        expected_access_audits=expected_access_audits,
    )
    return holdout_reassessment._build_authorized_holdout_report(
        pilot=pilot,
        pilot_bytes=(canonical_json(pilot) + "\n").encode("utf-8"),
        layout=ReassessmentRunLayout.for_run(
            RUN_ID,
            benchmark_root=tmp_path / "benchmark",
        ),
        audit={"satisfied": True},
        authorized_run=authorized,
        reviewed_corpus=_synthetic_reviewed_corpus(authorized),
    )


def test_authorized_holdout_ingestion_and_replay_selection_without_corpus_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(b"synthetic environment").hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    layout = ReassessmentRunLayout.for_run(
        RUN_ID,
        benchmark_root=tmp_path / "benchmark",
    )
    layout.pilot_report.parent.mkdir(parents=True)
    layout.pilot_report.write_text(
        canonical_json(pilot) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        holdout_reassessment,
        "load_pilot_reassessment_report",
        lambda *_args, **_kwargs: pilot,
    )
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "synthetic-holdout-execution",
    )
    synthetic_corpus = _synthetic_reviewed_corpus(authorized)
    synthetic_manifest = synthetic_corpus.manifest
    monkeypatch.setattr(
        holdout_reassessment,
        "load_manifest",
        lambda *_args, **_kwargs: synthetic_manifest,
    )
    monkeypatch.setattr(
        holdout_reassessment,
        "load_reviewed_corpus",
        lambda *_args, **_kwargs: synthetic_corpus,
    )
    monkeypatch.setattr(
        holdout_reassessment,
        "corpus_manifest_sha256",
        lambda *_args, **_kwargs: FROZEN_CORPUS_MANIFEST_SHA256,
    )

    _install_synthetic_access_validator(
        monkeypatch,
        authorized=authorized,
    )

    report = holdout_reassessment.build_holdout_reassessment_report(
        repository_root=tmp_path,
        run_id=RUN_ID,
        benchmark_root=tmp_path / "benchmark",
        authorized_run=authorized,
    )
    assert report["status"] == "incomplete"
    assert report["outcomes"]["status"] == "complete"
    assert report["outcomes"]["observed_pair_count"] == 20
    assert report["frozen_execution_contract"]["environment_sha256"] == (
        environment_sha256
    )
    assert report["prerequisite"]["authorization_sha256"] == (
        authorized.receipt.authorization_sha256
    )
    assert report["metrics"]["measured_domain_count"] == 1
    latency = next(
        item
        for item in report["metrics"]["domains"]
        if item["domain"] == "latency"
    )
    assert latency["status"] == "incomplete"
    assert latency["complete"] is False
    assert holdout_reassessment.validate_holdout_reassessment_report(
        report,
        repository_root=tmp_path,
        run_id=RUN_ID,
        benchmark_root=tmp_path / "benchmark",
    ) == report

    layout.holdout_report.write_text(
        canonical_json(report) + "\n",
        encoding="utf-8",
    )
    replay = reassessment_reports._build_pending_measured_replay_index(
        tmp_path,
        report,
        layout=layout,
    )
    assert replay["status"] == "pending_required_replays"
    assert replay["source_binding"]["environment_sha256"] == (
        environment_sha256
    )
    assert replay["selection"]["required_success_replay_count"] == 0
    assert replay["selection"]["required_sampled_failure_replay_count"] == 1
    assert replay["execution"]["replay_claimed"] is False


def test_authorized_report_rejects_missing_current_variant_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(b"missing route").hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "missing-route-execution",
    )
    results = list(authorized.execution.results)
    index = next(
        index
        for index, result in enumerate(results)
        if result.variant_id == "A1"
    )
    assert results[index].stages[-1].stage is StageName.KERNEL
    results[index] = CaseResultRecord.from_stages(
        results[index].stages[:-1]
    )
    forged = _rebind_authorized_run(
        authorized,
        execution=replace(
            authorized.execution,
            results=tuple(results),
        ),
    )

    with pytest.raises(
        holdout_reassessment.HoldoutReassessmentError,
        match="graph or cache isolation",
    ):
        _build_synthetic_authorized_report(
            tmp_path,
            monkeypatch,
            pilot=pilot,
            authorized=forged,
        )


def test_authorized_report_rejects_reordered_graph_invocations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(b"reordered route").hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "reordered-route-execution",
    )
    results = list(authorized.execution.results)
    index = next(
        index
        for index, result in enumerate(results)
        if result.variant_id == "A1"
    )
    target = results[index]
    first, second = target.stages[:2]
    first_index = first.provenance.effective_identity[
        "graph_invocation_index"
    ]
    second_index = second.provenance.effective_identity[
        "graph_invocation_index"
    ]
    reordered_first = replace(
        first,
        provenance=replace(
            first.provenance,
            effective_identity={
                **dict(first.provenance.effective_identity),
                "graph_invocation_index": second_index,
            },
        ),
    )
    reordered_second = replace(
        second,
        provenance=replace(
            second.provenance,
            effective_identity={
                **dict(second.provenance.effective_identity),
                "graph_invocation_index": first_index,
            },
        ),
    )
    results[index] = CaseResultRecord.from_stages(
        (
            reordered_first,
            reordered_second,
            *target.stages[2:],
        )
    )
    forged = _rebind_authorized_run(
        authorized,
        execution=replace(
            authorized.execution,
            results=tuple(results),
        ),
    )

    with pytest.raises(
        holdout_reassessment.HoldoutReassessmentError,
        match="graph or cache isolation",
    ):
        _build_synthetic_authorized_report(
            tmp_path,
            monkeypatch,
            pilot=pilot,
            authorized=forged,
        )


def test_authorized_report_rejects_cold_warm_backend_identity_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(b"cache identity drift").hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "cache-drift-execution",
    )
    results = list(authorized.execution.results)
    index = next(
        index
        for index, result in enumerate(results)
        if result.variant_id == "A1"
        and result.cache_mode is CacheMode.WARM
    )
    target = results[index]
    kernel = target.stages[-1]
    drifted_kernel = replace(
        kernel,
        provenance=replace(
            kernel.provenance,
            effective_identity={
                **dict(kernel.provenance.effective_identity),
                "backend_revision": "unfrozen-warm-backend",
            },
        ),
    )
    results[index] = CaseResultRecord.from_stages(
        (*target.stages[:-1], drifted_kernel)
    )
    forged = _rebind_authorized_run(
        authorized,
        execution=replace(
            authorized.execution,
            results=tuple(results),
        ),
    )

    with pytest.raises(
        holdout_reassessment.HoldoutReassessmentError,
        match="graph or cache isolation",
    ):
        _build_synthetic_authorized_report(
            tmp_path,
            monkeypatch,
            pilot=pilot,
            authorized=forged,
        )


def test_authorized_report_rejects_rehashed_invented_access_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(b"invented access audit").hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "invented-audit-execution",
    )
    original_audits = authorized.access_audits
    invented = original_audits[0].to_dict()
    invented["policy_sha256"] = hashlib.sha256(
        b"invented post-access policy"
    ).hexdigest()
    invented["audit_sha256"] = _sha(
        {
            key: value
            for key, value in invented.items()
            if key != "audit_sha256"
        }
    )
    invented_audits = (
        HoldoutAccessAudit.from_dict(invented),
        *original_audits[1:],
    )
    forged = _rebind_authorized_run(
        authorized,
        access_audits=invented_audits,
    )

    with pytest.raises(
        holdout_reassessment.HoldoutReassessmentError,
        match="access audits are invalid",
    ):
        _build_synthetic_authorized_report(
            tmp_path,
            monkeypatch,
            pilot=pilot,
            authorized=forged,
            expected_access_audits=original_audits,
        )


def test_holdout_safety_counts_only_unsupported_as_invalid_control(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_sha256 = hashlib.sha256(
        b"unsupported-only safety controls"
    ).hexdigest()
    pilot = _authorized_pilot(environment_sha256)
    authorized = _synthetic_authorized_run(
        pilot,
        environment_sha256,
        output_root=tmp_path / "safety-classification-execution",
        disproved_case_ordinals=(1,),
    )
    accepted_case_ids = {"synthetic-h01", "synthetic-h02"}
    results = tuple(
        _accept_terminal_kernel(
            result,
            environment_sha256=environment_sha256,
        )
        if (
            result.case_id in accepted_case_ids
            and result.variant_id == "A1"
            and result.cache_mode is CacheMode.COLD
        )
        else result
        for result in authorized.execution.results
    )
    rebound = _rebind_authorized_run(
        authorized,
        execution=replace(
            authorized.execution,
            results=results,
        ),
    )

    report = _build_synthetic_authorized_report(
        tmp_path,
        monkeypatch,
        pilot=pilot,
        authorized=rebound,
    )
    safety = next(
        domain
        for domain in report["metrics"]["domains"]
        if domain["domain"] == "safety"
    )
    assert safety["values"][
        "invalid_control_kernel_false_positive_count"
    ] == 1
    assert report["outcomes"]["kernel_verified_success_count"] == 2


def test_holdout_safety_reads_raw_terminal_kernel_acceptance() -> None:
    environment_sha256 = hashlib.sha256(b"safety environment").hexdigest()
    common = {
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "run_id": RUN_ID,
        "case_id": "synthetic-h01",
        "case_manifest_sha256": FROZEN_CORPUS_MANIFEST_SHA256,
        "variant_id": "A1",
        "split": Split.HOLDOUT,
        "cache_mode": CacheMode.COLD,
        "adapter_version": "v1",
    }
    compiler = StageRecord.create(
        **common,
        stage=StageName.COMPILER,
        status=StageStatus.FAILED,
        provenance=StageProvenance(
            schema=STAGE_PROVENANCE_SCHEMA,
            adapter_id="synthetic-compiler",
            adapter_version="v1",
            source=("raw-safety-test",),
            requested_identity={"component": "compiler"},
            effective_identity={"graph_invoked": True},
            input_sha256="f" * 64,
            environment_sha256=environment_sha256,
        ),
        telemetry=TelemetryRecord(resource_lane=ResourceLane.CPU),
        failure_code=FailureCode.CANONICAL_IR_REJECTION,
        failure_detail="blocking compiler failure",
    )
    receipt = _native_kernel_receipt(
        case_id="synthetic-h01",
        variant_id="A1",
        cache_mode=CacheMode.COLD,
        input_sha256="e" * 64,
        environment_sha256=environment_sha256,
        accepted=True,
        candidate_artifact_sha256=compiler.digest,
    )
    receipt_sha256 = str(receipt["receipt_sha256"])
    kernel = StageRecord.create(
        **common,
        stage=StageName.KERNEL,
        status=StageStatus.SUCCESS,
        provenance=StageProvenance(
            schema=STAGE_PROVENANCE_SCHEMA,
            adapter_id="synthetic-kernel",
            adapter_version="v1",
            source=("raw-safety-test",),
            requested_identity={"component": "kernel"},
            effective_identity={
                "graph_invoked": True,
                "consumed_artifact_sha256": [compiler.digest],
            },
            input_sha256="e" * 64,
            environment_sha256=environment_sha256,
            upstream_stage_digests=(compiler.digest,),
        ),
        telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
        data=receipt,
        kernel_accepted=True,
        kernel_receipt_sha256=receipt_sha256,
    )
    result = CaseResultRecord.from_stages((compiler, kernel))

    assert result.kernel_accepted is False
    assert result.status.value == "rejected"
    assert holdout_reassessment._raw_terminal_kernel_accepted(result) is True
