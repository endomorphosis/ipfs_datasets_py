"""Synthetic, holdout-free coverage for the fresh downstream handoff."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from benchmarks.logic_pipeline import holdout_reassessment
from benchmarks.logic_pipeline import reassessment_reports
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    AblationRunResult,
    build_ablation_plan,
)
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    CaseResultRecord,
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
                "expected_class": "unsupported",
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
    results = []
    for job in plan.jobs:
        provenance = StageProvenance(
            schema=STAGE_PROVENANCE_SCHEMA,
            adapter_id="synthetic-kernel",
            adapter_version="v1",
            source=("synthetic-unopened-fixture",),
            requested_identity={"variant_id": job.variant_id},
            effective_identity={"graph_invoked": True},
            input_sha256=job.input_sha256,
            environment_sha256=environment_sha256,
        )
        stage = StageRecord.create(
            protocol_sha256=DEFAULT_PROTOCOL_SHA256,
            run_id=RUN_ID,
            case_id=job.case_id,
            case_manifest_sha256=FROZEN_CORPUS_MANIFEST_SHA256,
            variant_id=job.variant_id,
            split=Split.HOLDOUT,
            cache_mode=job.cache_mode,
            stage=StageName.KERNEL,
            adapter_version="v1",
            status=StageStatus.SUCCESS,
            provenance=provenance,
            telemetry=TelemetryRecord(
                wall_time_ms=1.0,
                cpu_time_ms=0.5,
                peak_memory_bytes=1024,
                resource_lane=ResourceLane.KERNEL,
            ),
            data={"accepted": False},
        )
        results.append(CaseResultRecord.from_stages((stage,)))
    execution = AblationRunResult(
        plan=plan,
        contracts=plan.run_contracts,
        results=tuple(results),
        executed_job_ids=tuple(job.job_id for job in plan.jobs),
        resumed_job_ids=(),
        output_root=Path("."),
    )
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
            hashlib.sha256(f"audit-{index}".encode("utf-8")).hexdigest()
            for index, _contract in enumerate(plan.run_contracts)
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
    return AuthorizedHoldoutRun(execution, receipt)


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
    authorized = _synthetic_authorized_run(pilot, environment_sha256)
    jobs_by_case = {
        job.case_id: job for job in authorized.execution.plan.jobs
    }
    synthetic_manifest = SimpleNamespace(
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
    monkeypatch.setattr(
        holdout_reassessment,
        "load_manifest",
        lambda *_args, **_kwargs: synthetic_manifest,
    )
    monkeypatch.setattr(
        holdout_reassessment,
        "corpus_manifest_sha256",
        lambda *_args, **_kwargs: FROZEN_CORPUS_MANIFEST_SHA256,
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
